#!/usr/bin/env python3
"""C1 ownership candidate; hardware/checked sync stages are added separately."""
from source_utils import function, replace

OWNERSHIP_HELPERS = '''/* Controller-locked producers borrow before dropping the controller lock. */
static void pl330_error_locked(struct pl330_dmac *pl330, int error)
{
	if (!pl330->lifecycle_error)
		pl330->lifecycle_error = error;
}

static void pl330_pm_error_locked(struct pl330_dmac *pl330, int error)
{
	pl330_error_locked(pl330, error);
	pl330->pm_failed = true;
}

static struct dma_pl330_desc *pl330_desc_get(struct dma_pl330_desc *desc)
{
	if (!desc || !refcount_inc_not_zero(&desc->refs))
		return NULL;
	atomic_inc(&desc->owner_pch->producers);
	return desc;
}

static void pl330_desc_put(struct dma_pl330_desc *desc)
{
	struct dma_pl330_chan *owner = desc->owner_pch;

	/* The queue/preparation owner reference remains until checked release. */
	WARN_ON(refcount_dec_and_test(&desc->refs));
	atomic_dec(&owner->producers);
	wake_up_all(&owner->drain_wait);
	wake_up_all(&owner->dmac->drain_wait);
}

/* No channel/controller lock may be held while taking the public pool lock. */
static void pl330_desc_release(struct pl330_dmac *pl330,
			       struct dma_pl330_desc *desc)
{
	unsigned long flags;

	if (WARN_ON(refcount_read(&desc->refs) != 1))
		return;
	refcount_dec_and_test(&desc->refs);
	if (desc->prepared_owned) {
		atomic_dec(&desc->owner_pch->prepared_descs);
		desc->prepared_owned = false;
	}
	dma_descriptor_unmap(&desc->txd);
	desc->status = FREE;
	desc->pchan = NULL;
	desc->owner_pch = NULL;
	spin_lock_irqsave(&pl330->pool_lock, flags);
	list_add_tail(&desc->node, &pl330->desc_pool);
	spin_unlock_irqrestore(&pl330->pool_lock, flags);
}

static void __pl330_giveback_desc(struct pl330_dmac *pl330,
				struct dma_pl330_desc *first)
{
	struct dma_pl330_desc *desc;

	if (!first)
		return;
	while (!list_empty(&first->node)) {
		desc = list_first_entry(&first->node, struct dma_pl330_desc, node);
		list_del_init(&desc->node);
		pl330_desc_release(pl330, desc);
	}
	INIT_LIST_HEAD(&first->node);
	pl330_desc_release(pl330, first);
}

static void pl330_schedule_locked(struct dma_pl330_chan *pch)
{
	if (pch->quiescing || READ_ONCE(pch->dmac->lifecycle_error))
		return;
	if (pch->runner_active) {
		pch->rerun = true;
		return;
	}
	if (!pch->tasklet_queued)
		pch->tasklet_epoch = pch->epoch;
	pch->tasklet_queued = true;
	tasklet_schedule(&pch->task);
}

'''

RUNNER = '''static void pl330_run(struct dma_pl330_chan *pch, bool from_tasklet,
			 u64 expected_epoch)
{
	struct dma_pl330_desc *desc;
	struct dmaengine_desc_callback cb;
	unsigned long flags;
	u64 epoch;

	spin_lock_irqsave(&pch->lock, flags);
	if (from_tasklet)
		pch->tasklet_queued = false;
	if (pch->quiescing || pch->epoch != expected_epoch ||
	    READ_ONCE(pch->dmac->lifecycle_error) || !pch->thread)
		goto unlock;
	if (pch->runner_active) {
		pch->rerun = true;
		goto unlock;
	}
	pch->runner_active = true;
	atomic_inc(&pch->runners);
	epoch = pch->epoch;

again:
	pch->rerun = false;
restart:
	if (pch->quiescing || pch->epoch != epoch || READ_ONCE(pch->dmac->lifecycle_error))
		goto done;
	/* Never retain a list iterator across a callback's unlocked interval. */
	list_for_each_entry(desc, &pch->work_list, node) {
		if (desc->status != DONE)
			continue;
		if (desc->cyclic) {
			desc->status = BUSY;
		} else {
			dma_cookie_complete(&desc->txd);
			desc->status = RETIRED;
			list_move_tail(&desc->node, &pch->retired_list);
		}
		pl330_desc_get(desc);
		dmaengine_desc_get_callback(&desc->txd, &cb);
		spin_unlock_irqrestore(&pch->lock, flags);
		if (dmaengine_desc_callback_valid(&cb))
			dmaengine_desc_callback_invoke(&cb, NULL);
		pl330_desc_put(desc);
		spin_lock_irqsave(&pch->lock, flags);
		goto restart;
	}

	fill_queue(pch);
	spin_lock(&pch->dmac->lock);
	/* Another channel may have failed PM after the entry check. */
	if (pch->dmac->lifecycle_error || !pch->thread->accept_callbacks) {
		spin_unlock(&pch->dmac->lock);
		goto done;
	}
	if (list_empty(&pch->work_list)) {
		_stop(pch->thread);
		pch->active = false;
	} else {
		_start(pch->thread);
	}
	spin_unlock(&pch->dmac->lock);
	if (pch->rerun)
		goto again;
done:
	pch->runner_active = false;
	atomic_dec(&pch->runners);
unlock:
	spin_unlock_irqrestore(&pch->lock, flags);
	wake_up_all(&pch->drain_wait);
}

static void pl330_tasklet(struct tasklet_struct *t)
{
	struct dma_pl330_chan *pch = from_tasklet(pch, t, task);

	pl330_run(pch, true, READ_ONCE(pch->tasklet_epoch));
}'''

TERMINATE = '''static int pl330_terminate_all(struct dma_chan *chan)
{
	struct dma_pl330_chan *pch = to_pchan(chan);
	struct pl330_dmac *pl330 = pch->dmac;
	struct dma_pl330_desc *desc, *next;
	unsigned long flags;
	bool put_pm = false, failed_get = false;
	int ret;

	/* This controller uses IRQ-safe PM, but PM is never inside a spinlock. */
	ret = pm_runtime_get_sync(pl330->ddma.dev);
	spin_lock_irqsave(&pch->lock, flags);
	spin_lock(&pl330->lock);
	if (ret < 0) {
		pl330_pm_error_locked(pl330, ret);
		failed_get = true;
	}
	spin_unlock(&pl330->lock);
	if (ret >= 0 && !pch->pm_ref_held && !READ_ONCE(pl330->lifecycle_error))
		pch->pm_ref_held = true;
	else if (ret >= 0)
		put_pm = true;
	if (!pch->quiescing) {
		pch->quiescing = true;
		pch->epoch++;
	}
	pch->rerun = false;
	spin_lock(&pl330->lock);
	if (pch->thread) {
		pch->thread->accept_callbacks = false;
		if (!pl330->pm_failed)
			_stop(pch->thread);
		/* Revoke queued fault work for this physical thread at cutoff. */
		pl330->dmac_tbd.reset_chan &= ~(1U << pch->thread->id);
		pch->thread->req[0].desc = NULL;
		pch->thread->req[1].desc = NULL;
		pch->thread->req_running = -1;
	}
	list_for_each_entry_safe(desc, next, &pl330->req_done, rqd) {
		if (desc->owner_pch == pch) {
			list_del_init(&desc->rqd);
			pl330_desc_put(desc);
		}
	}
	spin_unlock(&pl330->lock);
	pch->active = false;
	list_splice_tail_init(&pch->submitted_list, &pch->retired_list);
	list_splice_tail_init(&pch->work_list, &pch->retired_list);
	list_splice_tail_init(&pch->completed_list, &pch->retired_list);
	list_for_each_entry(desc, &pch->retired_list, node) {
		desc->status = RETIRED;
		/* Noncyclic DONE was completed before its callback; cookie is then 0. */
		if (desc->txd.cookie >= DMA_MIN_COOKIE)
			dma_cookie_complete(&desc->txd);
	}
	spin_unlock_irqrestore(&pch->lock, flags);
	if (failed_get)
		pm_runtime_put_noidle(pl330->ddma.dev);
	if (put_pm) {
		pm_runtime_mark_last_busy(pl330->ddma.dev);
		pm_runtime_put_autosuspend(pl330->ddma.dev);
	}
	wake_up_all(&pch->drain_wait);
	return READ_ONCE(pl330->lifecycle_error);
}'''

ISSUE = '''static void pl330_issue_pending(struct dma_chan *chan)
{
	struct dma_pl330_chan *pch = to_pchan(chan);
	unsigned long flags;
	bool put_pm = false, run = false;
	u64 epoch;
	int ret;

	/* Admission covers PM and the unlocked interval before the direct runner. */
	spin_lock_irqsave(&pch->lock, flags);
	if (pch->quiescing || READ_ONCE(pch->dmac->lifecycle_error) ||
	    !pch->thread || list_empty(&pch->submitted_list)) {
		spin_unlock_irqrestore(&pch->lock, flags);
		return;
	}
	epoch = pch->epoch;
	atomic_inc(&pch->issuers);
	spin_unlock_irqrestore(&pch->lock, flags);
	ret = pm_runtime_get_sync(pch->dmac->ddma.dev);
	spin_lock_irqsave(&pch->lock, flags);
	if (ret < 0) {
		spin_lock(&pch->dmac->lock);
		pl330_pm_error_locked(pch->dmac, ret);
		spin_unlock(&pch->dmac->lock);
	}
	if (ret < 0 || pch->quiescing || pch->epoch != epoch ||
	    READ_ONCE(pch->dmac->lifecycle_error) ||
	    list_empty(&pch->submitted_list)) {
		put_pm = true;
		goto unlock;
	}
	if (!pch->pm_ref_held)
		pch->pm_ref_held = true;
	else
		put_pm = true;
	pch->active = true;
	list_splice_tail_init(&pch->submitted_list, &pch->work_list);
	run = true;
unlock:
	spin_unlock_irqrestore(&pch->lock, flags);
	if (put_pm) {
		if (ret < 0)
			pm_runtime_put_noidle(pch->dmac->ddma.dev);
		else {
			pm_runtime_mark_last_busy(pch->dmac->ddma.dev);
			pm_runtime_put_autosuspend(pch->dmac->ddma.dev);
		}
	}
	/* Preserve DMA-before-CPU startup without a second concurrent runner. */
	if (run)
		pl330_run(pch, false, epoch);
	atomic_dec(&pch->issuers);
	wake_up_all(&pch->drain_wait);
}'''


def ownership(source):
    source = replace(source, "#include <linux/dma-mapping.h>", "#include <linux/dma-mapping.h>\n#include <linux/refcount.h>\n#include <linux/wait.h>\n#include <linux/mutex.h>")
    source = replace(source, "\tDONE,\n};", "\tDONE,\n\t/* Owner retained until software drain and STOPPED are proved. */\n\tRETIRED,\n};")
    # The only req_running declaration identifies the physical thread.
    source = replace(source, "\tint req_running;", "\tint req_running;\n\tbool accept_callbacks;\n\tstruct dma_pl330_chan *owner_pch;")
    source = replace(source, "\tbool active;\n};", """	bool active;
	/* Lifecycle fields protected by lock; producers/runners are waitable. */
	u64 epoch;
	bool quiescing;
	bool runner_active;
	bool rerun;
	bool tasklet_queued;
	u64 tasklet_epoch;
	bool pm_ref_held;
	struct list_head retired_list;
	atomic_t producers;
	atomic_t runners;
	atomic_t preparations;
	atomic_t prepared_descs;
	atomic_t faults;
	atomic_t issuers;
	bool preparing;
	struct dma_slave_config fifo_config;
	enum dma_transfer_direction prepared_direction;
	wait_queue_head_t drain_wait;
	struct mutex sync_mutex;
};""")
    source = replace(source, "\tstruct reset_control\t*rstc;", "\t/* First hardware lifecycle error, protected by controller lock. */\n\tint lifecycle_error;\n\tbool pm_failed;\n\tatomic_t producers;\n\twait_queue_head_t drain_wait;\n\n\tstruct reset_control\t*rstc;")
    source = replace(source, "\tstruct dma_pl330_chan *pchan;", "\tstruct dma_pl330_chan *pchan;\n\t/* Immutable until the final borrowed reference has drained. */\n\tstruct dma_pl330_chan *owner_pch;\n\tu64 owner_epoch;\n\trefcount_t refs;\n\tbool prepared_owned;")
    old = function(source, "__pl330_giveback_desc")
    source = replace(source, old, "")
    old = function(source, "dma_pl330_rqcb")
    new = '''static void dma_pl330_rqcb(struct dma_pl330_desc *desc, enum pl330_op_err err)
{
	struct dma_pl330_chan *pch;
	unsigned long flags;

	if (!desc)
		return;
	pch = desc->owner_pch;
	spin_lock_irqsave(&pch->lock, flags);
	if (!pch->quiescing && desc->owner_epoch == pch->epoch &&
	    !READ_ONCE(pch->dmac->lifecycle_error)) {
		desc->status = DONE;
		pl330_schedule_locked(pch);
	}
	spin_unlock_irqrestore(&pch->lock, flags);
	pl330_desc_put(desc);
}'''
    source = replace(source, old, OWNERSHIP_HELPERS + new)
    old = function(source, "pl330_dotask")
    old_first_lock = "\n\tspin_lock_irqsave(&pl330->lock, flags);"
    new = replace(old, old_first_lock, "\tatomic_inc(&pl330->producers);\n" + old_first_lock + "\n\tif (pl330->pm_failed) {\n\t\tpl330->dmac_tbd.reset_dmac = false;\n\t\tpl330->dmac_tbd.reset_mngr = false;\n\t\tpl330->dmac_tbd.reset_chan = 0;\n\t\tgoto out;\n\t}")
    new = replace(new, "\t\t\t_stop(thrd);", "\t\t\tstruct dma_pl330_desc *first, *second;\n\t\t\tstruct dma_pl330_chan *owner = thrd->owner_pch;\n\n\t\t\tif (!thrd->accept_callbacks) {\n\t\t\t\tpl330->dmac_tbd.reset_chan &= ~(1U << i);\n\t\t\t\tcontinue;\n\t\t\t}\n\t\t\tatomic_inc(&owner->faults);\n\t\t\t_stop(thrd);")
    start = new.index("\t\t\tspin_unlock_irqrestore(&pl330->lock, flags);")
    end = new.index("\t\t\t/* Clear the reset flag */", start)
    new = new[:start] + '''			/* Capture both before unlocking; req[] may belong to a new epoch later. */
			first = thrd->accept_callbacks ?
				pl330_desc_get(thrd->req[1 - thrd->lstenq].desc) : NULL;
			second = thrd->accept_callbacks ?
				pl330_desc_get(thrd->req[thrd->lstenq].desc) : NULL;
			thrd->req[0].desc = NULL;
			thrd->req[1].desc = NULL;
			thrd->req_running = -1;
			/* Finish the captured epoch's controller cleanup before any put. */
			pl330->dmac_tbd.reset_chan &= ~(1U << i);
			spin_unlock_irqrestore(&pl330->lock, flags);
			dma_pl330_rqcb(first, err);
			dma_pl330_rqcb(second, err);
			spin_lock_irqsave(&pl330->lock, flags);

''' + new[end:]
    new = replace(new, "\t\t\t/* Clear the reset flag */\n\t\t\tpl330->dmac_tbd.reset_chan &= ~(1 << i);", "\t\t\t/* A newly published reset bit belongs to the next captured work. */")
    new = replace(new, "\t\t\t/* A newly published reset bit belongs to the next captured work. */", "\t\t\t/* The lease includes this final controller-lock acquisition. */\n\t\t\tatomic_dec(&owner->faults);\n\t\t\twake_up_all(&owner->drain_wait);\n\t\t\t/* A newly published reset bit belongs to the next captured work. */")
    new = replace(new, "\t\tif (pl330->dmac_tbd.reset_chan & (1 << i)) {", "\t\t/* PM can fail on another channel while a prior rqcb was unlocked. */\n\t\tif (pl330->pm_failed)\n\t\t\tgoto out;\n\t\tif (pl330->dmac_tbd.reset_chan & (1 << i)) {")
    new = replace(new, "\tif (pl330->dmac_tbd.reset_dmac) {", "\tif (pl330->dmac_tbd.reset_dmac) {\n\t\tpl330_error_locked(pl330, -EIO);")
    new = replace(new, "\tif (pl330->dmac_tbd.reset_mngr) {", "\tif (pl330->dmac_tbd.reset_mngr) {\n\t\tpl330_error_locked(pl330, -EIO);")
    new = replace(new, "\tspin_unlock_irqrestore(&pl330->lock, flags);\n\n\treturn;", "out:\n\tspin_unlock_irqrestore(&pl330->lock, flags);\n\tatomic_dec(&pl330->producers);\n\twake_up_all(&pl330->drain_wait);\n\n\treturn;")
    source = replace(source, old, new)
    old = function(source, "pl330_update")
    new = replace(old, "\n\tspin_lock_irqsave(&pl330->lock, flags);", "\n\tatomic_inc(&pl330->producers);\n\tspin_lock_irqsave(&pl330->lock, flags);\n\tif (pl330->pm_failed)\n\t\tgoto updt_exit;")
    new = replace(new, "\t\t\tif (descdone) {", "\t\t\tif (descdone && thrd->accept_callbacks) {")
    new = replace(new, "\t\t\t\tlist_add_tail(&descdone->rqd, &pl330->req_done);", """				if (list_empty(&descdone->rqd)) {
					pl330_desc_get(descdone);
					list_add_tail(&descdone->rqd, &pl330->req_done);
				}""")
    new = replace(new, "\t\tlist_del(&descdone->rqd);", "\t\tlist_del_init(&descdone->rqd);")
    new = replace(new, "\t\t\t\t\t_start(thrd);", "\t\t\t\t\tif (!pl330->lifecycle_error)\n\t\t\t\t\t\t_start(thrd);")
    new = replace(new, "\tif (val)\n\t\tpl330->dmac_tbd.reset_mngr = true;\n\telse\n\t\tpl330->dmac_tbd.reset_mngr = false;", "\tif (val) {\n\t\tpl330_error_locked(pl330, -EIO);\n\t\tpl330->dmac_tbd.reset_mngr = true;\n\t}")
    new = replace(new, "\tpl330->dmac_tbd.reset_chan |= val;", "\t/* Channel fault publication is admitted only through its current gate. */")
    new = replace(new, "\t\t\tif (val & (1 << i)) {", "\t\t\tif ((val & (1 << i)) && pl330->channels[i].accept_callbacks) {\n\t\t\t\tpl330->dmac_tbd.reset_chan |= 1U << i;\n\t\t\t\tpl330_error_locked(pl330, -EIO);")
    new = replace(new, "\t\tpl330->dmac_tbd.reset_dmac = true;", "\t\tpl330_error_locked(pl330, -EIO);\n\t\tpl330->dmac_tbd.reset_dmac = true;")
    new = replace(new, "updt_exit:\n\tspin_unlock_irqrestore(&pl330->lock, flags);\n\n\tif (pl330->dmac_tbd.reset_dmac", "updt_exit:\n\tif (pl330->dmac_tbd.reset_dmac")
    new = replace(new, "\tatomic_dec(&pl330->producers);", "\tspin_unlock_irqrestore(&pl330->lock, flags);\n\tatomic_dec(&pl330->producers);") if "\tatomic_dec(&pl330->producers);" in new else new
    new = replace(new, "\treturn ret;", "\tatomic_dec(&pl330->producers);\n\twake_up_all(&pl330->drain_wait);\n\treturn ret;")
    new = replace(new, "\tatomic_dec(&pl330->producers);\n\twake_up_all(&pl330->drain_wait);\n\treturn ret;", "\tspin_unlock_irqrestore(&pl330->lock, flags);\n\tatomic_dec(&pl330->producers);\n\twake_up_all(&pl330->drain_wait);\n\treturn ret;")
    source = replace(source, old, new)
    old = function(source, "pl330_submit_req")
    new = replace(old, "\tspin_lock_irqsave(&pl330->lock, flags);", "\tspin_lock_irqsave(&pl330->lock, flags);\n\tif (pl330->lifecycle_error || !thrd->accept_callbacks ||\n\t    desc->owner_pch != thrd->owner_pch ||\n\t    desc->owner_epoch != thrd->owner_pch->epoch) {\n\t\tret = -EIO;\n\t\tgoto xfer_exit;\n\t}")
    source = replace(source, old, new)
    old = function(source, "fill_queue")
    new = replace(old, "\t\t\ttasklet_schedule(&pch->task);", "\t\t\tspin_lock(&pch->dmac->lock);\n\t\t\tpl330_error_locked(pch->dmac, ret);\n\t\t\tspin_unlock(&pch->dmac->lock);\n\t\t\tpl330_schedule_locked(pch);")
    source = replace(source, old, new)
    for name, body in [("pl330_tasklet", RUNNER), ("pl330_terminate_all", TERMINATE), ("pl330_issue_pending", ISSUE)]:
        source = replace(source, function(source, name), body)
    # There is no lockless unborrowed rqcb in physical-channel release.
    old = function(source, "pl330_release_channel")
    new = replace(old, "\tdma_pl330_rqcb(thrd->req[1 - thrd->lstenq].desc, PL330_ERR_ABORT);\n\tdma_pl330_rqcb(thrd->req[thrd->lstenq].desc, PL330_ERR_ABORT);", "\tWARN_ON(thrd->req[0].desc || thrd->req[1].desc);\n\tthrd->accept_callbacks = false;")
    source = replace(source, old, new)
    old = function(source, "pl330_tx_submit")
    new = replace(old, "\tspin_lock_irqsave(&pch->lock, flags);", """	spin_lock_irqsave(&pch->lock, flags);
	if (pch->quiescing || READ_ONCE(pch->dmac->lifecycle_error) ||
	    last->owner_pch != pch || last->owner_epoch != pch->epoch) {
		goto reject;
	}
	list_for_each_entry(desc, &last->node, node) {
		if (desc->owner_pch != pch || desc->owner_epoch != pch->epoch)
			goto reject;
	}
	goto valid;
reject:
		spin_unlock_irqrestore(&pch->lock, flags);
		__pl330_giveback_desc(pch->dmac, last);
		return -EIO;
valid:;""")
    new = replace(new, "\t\tdma_cookie_assign(&desc->txd);", "\t\tif (desc->prepared_owned) {\n\t\t\tatomic_dec(&pch->prepared_descs);\n\t\t\tdesc->prepared_owned = false;\n\t\t}\n\t\tdma_cookie_assign(&desc->txd);")
    new = replace(new, "\tlast->last = true;", "\tif (last->prepared_owned) {\n\t\tatomic_dec(&pch->prepared_descs);\n\t\tlast->prepared_owned = false;\n\t}\n\tlast->last = true;")
    source = replace(source, old, new)
    old = function(source, "_init_desc")
    new = replace(old, "\tINIT_LIST_HEAD(&desc->node);", "\tINIT_LIST_HEAD(&desc->node);\n\tINIT_LIST_HEAD(&desc->rqd);\n\trefcount_set(&desc->refs, 0);")
    source = replace(source, old, new)
    old = function(source, "pluck_desc")
    new = replace(old, "\t\tdesc->txd.callback = NULL;", "\t\tdesc->txd.callback = NULL;\n\t\tdesc->txd.callback_result = NULL;\n\t\tdesc->txd.callback_param = NULL;")
    source = replace(source, old, new)
    old = function(source, "pl330_get_desc")
    new = replace(old, "\tstruct dma_pl330_desc *desc;", "\tstruct dma_pl330_desc *desc;\n\tunsigned long flags;")
    new = replace(new, "\t/* Pluck one desc", "\tif (READ_ONCE(pch->quiescing) || READ_ONCE(pl330->lifecycle_error))\n\t\treturn NULL;\n\n\t/* Pluck one desc")
    new = replace(new, "\t/* Initialize the descriptor */\n\tdesc->pchan = pch;", """	spin_lock_irqsave(&pch->lock, flags);
	if (pch->quiescing || READ_ONCE(pl330->lifecycle_error)) {
		spin_unlock_irqrestore(&pch->lock, flags);
		refcount_set(&desc->refs, 1);
		pl330_desc_release(pl330, desc);
		return NULL;
	}
	/* Initialize once per checkout, before transferring to the submit queue. */
	desc->pchan = pch;
	desc->owner_pch = pch;
	desc->owner_epoch = pch->epoch;
	refcount_set(&desc->refs, 1);
	desc->prepared_owned = true;
	atomic_inc(&pch->prepared_descs);
	spin_unlock_irqrestore(&pch->lock, flags);""")
    source = replace(source, old, new)
    old = function(source, "pl330_alloc_chan_resources")
    new = replace(old, "\tdma_cookie_init(chan);", "\tif (pl330->lifecycle_error) {\n\t\tspin_unlock_irqrestore(&pl330->lock, flags);\n\t\treturn pl330->lifecycle_error;\n\t}\n\tdma_cookie_init(chan);")
    new = replace(new, "\ttasklet_setup(&pch->task, pl330_tasklet);", "\tpch->thread->accept_callbacks = true;\n\ttasklet_setup(&pch->task, pl330_tasklet);")
    new = replace(new, "\tpch->thread->accept_callbacks = true;", "\tpch->thread->owner_pch = pch;\n\tpch->thread->accept_callbacks = true;")
    source = replace(source, old, new)
    source = replace(source, "\t\tINIT_LIST_HEAD(&pch->completed_list);", """		INIT_LIST_HEAD(&pch->completed_list);
		INIT_LIST_HEAD(&pch->retired_list);
		atomic_set(&pch->producers, 0);
		atomic_set(&pch->runners, 0);
		atomic_set(&pch->preparations, 0);
		atomic_set(&pch->prepared_descs, 0);
		atomic_set(&pch->faults, 0);
		atomic_set(&pch->issuers, 0);
		init_waitqueue_head(&pch->drain_wait);
		mutex_init(&pch->sync_mutex);""")
    source = replace(source, "\tpd = &pl330->ddma;", "\tatomic_set(&pl330->producers, 0);\n\tinit_waitqueue_head(&pl330->drain_wait);\n\tpd = &pl330->ddma;")
    return preparation(source)


PREPARATION_HELPERS = '''/* A preparation owns config/FIFO state until its complete chain is built. */
static bool pl330_fifo_config_same(struct dma_pl330_chan *pch,
				 enum dma_transfer_direction direction)
{
	const struct dma_slave_config *a = &pch->fifo_config;
	const struct dma_slave_config *b = &pch->slave_config;

#ifdef CONFIG_NO_GKI
	if (a->src_interlace_size != b->src_interlace_size ||
	    a->dst_interlace_size != b->dst_interlace_size)
		return false;
#endif
	if (direction == DMA_MEM_TO_DEV)
		return a->dst_addr == b->dst_addr &&
			a->dst_addr_width == b->dst_addr_width &&
			a->dst_maxburst == b->dst_maxburst;
	return a->src_addr == b->src_addr &&
		a->src_addr_width == b->src_addr_width &&
		a->src_maxburst == b->src_maxburst;
}

static bool pl330_prep_begin(struct dma_pl330_chan *pch,
			    enum dma_transfer_direction direction, bool slave,
			    u64 *epoch, bool *reuse_fifo)
{
	unsigned long flags;
	bool inflight;

	*reuse_fifo = false;
	spin_lock_irqsave(&pch->lock, flags);
	if (pch->quiescing || READ_ONCE(pch->dmac->lifecycle_error) || pch->preparing)
		goto reject;
	inflight = pch->active || !list_empty(&pch->submitted_list) ||
		!list_empty(&pch->work_list) || !list_empty(&pch->retired_list) ||
		atomic_read(&pch->prepared_descs);
	if (slave && inflight) {
		/* Queued SG with the identical immutable FIFO config remains legal. */
		if (pch->dir == DMA_NONE || pch->prepared_direction != direction ||
		    !pl330_fifo_config_same(pch, direction))
			goto reject;
		*reuse_fifo = true;
	}
	pch->preparing = true;
	atomic_inc(&pch->preparations);
	*epoch = pch->epoch;
	spin_unlock_irqrestore(&pch->lock, flags);
	return true;
reject:
	spin_unlock_irqrestore(&pch->lock, flags);
	return false;
}

static void pl330_prep_end(struct dma_pl330_chan *pch)
{
	unsigned long flags;

	spin_lock_irqsave(&pch->lock, flags);
	pch->preparing = false;
	atomic_dec(&pch->preparations);
	spin_unlock_irqrestore(&pch->lock, flags);
	wake_up_all(&pch->drain_wait);
	wake_up_all(&pch->dmac->drain_wait);
}

'''


def preparation(source):
    old = function(source, "pl330_config")
    new = replace(old, "\tmemcpy(&pch->slave_config, slave_config, sizeof(*slave_config));", '''	unsigned long flags;
	int ret = 0;

	spin_lock_irqsave(&pch->lock, flags);
	if (pch->quiescing || READ_ONCE(pch->dmac->lifecycle_error))
		ret = -EIO;
	else if (pch->preparing)
		ret = -EBUSY;
	else
		memcpy(&pch->slave_config, slave_config, sizeof(*slave_config));
	spin_unlock_irqrestore(&pch->lock, flags);''')
    new = replace(new, "\treturn 0;", "\treturn ret;")
    source = replace(source, old, new)
    old = function(source, "pl330_prep_dma_cyclic")
    new = replace(old, "\tdma_addr_t src = 0;", "\tdma_addr_t src = 0;\n\tu64 epoch;\n\tbool reuse_fifo;")
    new = replace(new, "\tif (len % period_len != 0)", "\tif (!len || !period_len || len % period_len != 0)")
    new = replace(new, "\tpl330_config_write(chan, &pch->slave_config, direction);\n\n\tif (!pl330_prep_slave_fifo(pch, direction))\n\t\treturn NULL;", '''	if (!pl330_prep_begin(pch, direction, true, &epoch, &reuse_fifo))
		return NULL;
	if (!reuse_fifo) {
		pl330_config_write(chan, &pch->slave_config, direction);
		if (!pl330_prep_slave_fifo(pch, direction))
			goto out;
		pch->fifo_config = pch->slave_config;
		pch->prepared_direction = direction;
	}''')
    new = replace(new, "\t\treturn NULL;\n\t}\n\n\tswitch (direction)", "\t\tgoto out;\n\t}\n\tif (desc->owner_epoch != epoch) {\n\t\t__pl330_giveback_desc(pch->dmac, desc);\n\t\tgoto out;\n\t}\n\n\tswitch (direction)")
    new = replace(new, "\treturn &desc->txd;", "\tpl330_prep_end(pch);\n\treturn &desc->txd;\nout:\n\tpl330_prep_end(pch);\n\treturn NULL;")
    source = replace(source, old, PREPARATION_HELPERS + new)
    old = function(source, "pl330_prep_slave_sg")
    new = replace(old, "\tint i;", "\tint i;\n\tu64 epoch;\n\tbool reuse_fifo;")
    new = replace(new, "\tpl330_config_write(chan, &pch->slave_config, direction);\n\n\tif (!pl330_prep_slave_fifo(pch, direction))\n\t\treturn NULL;", '''	if (!is_slave_direction(direction) ||
	    !pl330_prep_begin(pch, direction, true, &epoch, &reuse_fifo))
		return NULL;
	if (!reuse_fifo) {
		pl330_config_write(chan, &pch->slave_config, direction);
		if (!pl330_prep_slave_fifo(pch, direction))
			goto out;
		pch->fifo_config = pch->slave_config;
		pch->prepared_direction = direction;
	}''')
    new = replace(new, "\t\t\treturn NULL;", "\t\t\tgoto out;")
    new = replace(new, "\t\tif (!first)\n", "\t\tif (desc->owner_epoch != epoch) {\n\t\t\t__pl330_giveback_desc(pch->dmac, desc);\n\t\t\t__pl330_giveback_desc(pch->dmac, first);\n\t\t\tgoto out;\n\t\t}\n\n\t\tif (!first)\n")
    new = replace(new, "\treturn &desc->txd;", "\tpl330_prep_end(pch);\n\treturn &desc->txd;\nout:\n\tpl330_prep_end(pch);\n\treturn NULL;")
    source = replace(source, old, new)
    old = function(source, "pl330_prep_dma_memcpy")
    new = replace(old, "\tint burst;", "\tint burst;\n\tu64 epoch;\n\tbool reuse_fifo;")
    new = replace(new, "\tpl330 = pch->dmac;", "\tif (!pl330_prep_begin(pch, DMA_MEM_TO_MEM, false, &epoch, &reuse_fifo))\n\t\treturn NULL;\n\tpl330 = pch->dmac;")
    new = replace(new, "\tif (!desc)\n\t\treturn NULL;", "\tif (!desc)\n\t\tgoto out;\n\tif (desc->owner_epoch != epoch) {\n\t\t__pl330_giveback_desc(pl330, desc);\n\t\tgoto out;\n\t}")
    new = replace(new, "\treturn &desc->txd;", "\tpl330_prep_end(pch);\n\treturn &desc->txd;\nout:\n\tpl330_prep_end(pch);\n\treturn NULL;")
    source = replace(source, old, new)
    return source
