#!/usr/bin/env python3
"""Process-only retired metadata reclaim at a proved idle physical boundary."""
from source_utils import function,replace

SCHEDULE='''static void pl330_gc_schedule_locked(struct dma_pl330_chan *pch)
{
	if (pch->quiescing || READ_ONCE(pch->dmac->lifecycle_error) ||
	    READ_ONCE(pch->dmac->removing) || READ_ONCE(pch->dmac->system_suspended) ||
	    pch->gc_queued || atomic_read(&pch->gc_users) ||
	    list_empty(&pch->retired_list) || !list_empty(&pch->work_list) ||
	    !list_empty(&pch->submitted_list))
		return;
	pch->gc_queued = true;
	schedule_work(&pch->gc_work);
}

'''

WORK='''static void pl330_gc_work(struct work_struct *work)
{
	struct dma_pl330_chan *pch = container_of(work, struct dma_pl330_chan, gc_work);
	struct pl330_dmac *pl330 = pch->dmac;
	struct dma_pl330_desc *desc, *next;
	LIST_HEAD(reclaim);
	unsigned long flags;
	ktime_t deadline;
	bool put_owned = false, retry;
	int pm_ret;

	spin_lock_irqsave(&pch->lock, flags);
	pch->gc_queued = false;
	atomic_inc(&pch->gc_users);
	spin_unlock_irqrestore(&pch->lock, flags);
	pm_ret = pm_runtime_get_sync(pl330->ddma.dev);
	if (pm_ret < 0) {
		spin_lock_irqsave(&pl330->lock, flags);
		pl330_pm_error_locked(pl330, pm_ret);
		spin_unlock_irqrestore(&pl330->lock, flags);
		pm_runtime_put_noidle(pl330->ddma.dev);
		goto done;
	}
	deadline = ktime_add_ms(ktime_get(), 20);
	for (;;) {
		retry = false;
		spin_lock_irqsave(&pch->lock, flags);
		spin_lock(&pl330->lock);
		if (pch->quiescing || pl330->lifecycle_error || pl330->removing ||
		    pl330->system_suspended || !pch->thread ||
		    !list_empty(&pch->work_list) || !list_empty(&pch->submitted_list))
			goto unlock;
		/* Exclude this worker's sole gc_users lease from the old-user proof. */
		if (atomic_read(&pch->producers) || atomic_read(&pch->runners) ||
		    atomic_read(&pch->issuers) || atomic_read(&pch->operations) ||
		    atomic_read(&pch->preparations) || atomic_read(&pch->faults) ||
		    pch->tasklet_queued || pch->thread->req[0].desc ||
		    pch->thread->req[1].desc) {
			retry = true;
			goto unlock;
		}
		if ((readl(pl330->base + FSM) & 1) ||
		    (readl(pl330->base + FSC) & ((1U << pl330->pcfg.num_chan) - 1))) {
			pl330_error_locked(pl330, -EIO);
			goto unlock;
		}
		if (pl330->dmac_tbd.reset_dmac || pl330->dmac_tbd.reset_mngr ||
		    pl330->dmac_tbd.reset_chan ||
		    _state(pch->thread) != PL330_STATE_STOPPED) {
			retry = true;
			goto unlock;
		}
		list_for_each_entry(desc, &pch->retired_list, node)
			if (refcount_read(&desc->refs) != 1)
				goto unlock;
		/* No old request or old software user can reach these detached owners. */
		list_splice_tail_init(&pch->retired_list, &reclaim);
		if (pch->pm_ref_held) {
			pch->pm_ref_held = false;
			put_owned = true;
		}
unlock:
		spin_unlock(&pl330->lock);
		spin_unlock_irqrestore(&pch->lock, flags);
		if (!retry || ktime_compare(ktime_get(), deadline) >= 0)
			break;
		usleep_range(50, 100);
	}
	/* New admission may now publish a new request; it cannot reach this local list. */
	list_for_each_entry_safe(desc, next, &reclaim, node) {
		list_del_init(&desc->node);
		pl330_desc_release(pl330, desc);
	}
	if (put_owned) {
		pm_runtime_mark_last_busy(pl330->ddma.dev);
		pm_runtime_put_autosuspend(pl330->ddma.dev);
	}
	pm_runtime_mark_last_busy(pl330->ddma.dev);
	pm_runtime_put_autosuspend(pl330->ddma.dev);
done:
	spin_lock_irqsave(&pch->lock, flags);
	atomic_dec(&pch->gc_users);
	spin_unlock_irqrestore(&pch->lock, flags);
	wake_up_all(&pch->drain_wait);
}

'''


def idle_reclaim(source):
    source=replace(source,"#include <linux/mutex.h>", "#include <linux/mutex.h>\n#include <linux/workqueue.h>")
    source=replace(source,"\tstruct mutex sync_mutex;", "\tstruct mutex sync_mutex;\n\tstruct work_struct gc_work;\n\tbool gc_queued;\n\tatomic_t gc_users;")
    source=replace(source,"\t\tatomic_set(&pch->operations, 0);", "\t\tatomic_set(&pch->operations, 0);\n\t\tatomic_set(&pch->gc_users, 0);\n\t\tINIT_WORK(&pch->gc_work, pl330_gc_work);")
    old=function(source,"pl330_run")
    new=replace(old,"unlock:\n\tspin_unlock_irqrestore(&pch->lock, flags);", "unlock:\n\tpl330_gc_schedule_locked(pch);\n\tspin_unlock_irqrestore(&pch->lock, flags);")
    source=replace(source,old,SCHEDULE+new)
    old=function(source,"pl330_issue_pending")
    new=replace(old,"\tatomic_dec(&pch->issuers);", "\tspin_lock_irqsave(&pch->lock, flags);\n\tatomic_dec(&pch->issuers);\n\tpl330_gc_schedule_locked(pch);\n\tspin_unlock_irqrestore(&pch->lock, flags);")
    source=replace(source,old,new)
    source=replace(source,"\t\t!atomic_read(&pch->faults) && !pch->tasklet_queued;", "\t\t!atomic_read(&pch->faults) && !pch->tasklet_queued &&\n\t\t!atomic_read(&pch->gc_users) && !pch->gc_queued;")
    old=function(source,"pl330_sync_channel")
    source=replace(source,old,WORK+old)
    source=replace(source,"\ttasklet_kill(&pch->task);", "\tcancel_work_sync(&pch->gc_work);\n\ttasklet_kill(&pch->task);")
    return source
