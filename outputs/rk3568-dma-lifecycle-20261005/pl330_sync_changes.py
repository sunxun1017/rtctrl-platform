#!/usr/bin/env python3
"""Process-context software drain and hardware proof; checked API remains optional."""
from source_utils import function, replace

SYNC = '''static void __noreturn pl330_failstop(struct pl330_dmac *pl330,
				      const char *reason)
{
	/* Software owners cannot be released, and this kernel must not warm reboot. */
	panic_timeout = 0;
	panic("PL330 %s unsafe lifecycle: %s", dev_name(pl330->ddma.dev), reason);
}

static bool pl330_software_drained_locked(struct dma_pl330_chan *pch)
{
	return !atomic_read(&pch->producers) && !atomic_read(&pch->runners) &&
		!atomic_read(&pch->issuers) && !atomic_read(&pch->preparations) &&
		!atomic_read(&pch->faults) && !pch->tasklet_queued;
}

static bool pl330_software_drained(struct dma_pl330_chan *pch)
{
	unsigned long flags;
	bool drained;

	spin_lock_irqsave(&pch->lock, flags);
	drained = pl330_software_drained_locked(pch);
	spin_unlock_irqrestore(&pch->lock, flags);
	return drained;
}

/* A negative return is allowed only after every old software user has drained. */
static int pl330_synchronize_checked(struct dma_chan *chan)
{
	struct dma_pl330_chan *pch = to_pchan(chan);
	struct pl330_dmac *pl330 = pch->dmac;
	struct dma_pl330_desc *desc, *next;
	LIST_HEAD(reclaim);
	ktime_t deadline;
	unsigned long flags;
	bool put_pm = false, stopped;
	int ret;

	might_sleep();
	mutex_lock(&pch->sync_mutex);
	/* Also covers PREPARE/HW_FREE after a failed START with no stop_operating. */
	pl330_terminate_all(chan);
	if (!wait_event_timeout(pch->drain_wait, pl330_software_drained(pch),
				msecs_to_jiffies(500)))
		pl330_failstop(pl330, "software drain deadline");
	deadline = ktime_add_ms(ktime_get(), 20);
	for (;;) {
		spin_lock_irqsave(&pl330->lock, flags);
		ret = pl330->lifecycle_error;
		if (!ret && ((readl(pl330->base + FSM) & 1) ||
		    (readl(pl330->base + FSC) & ((1U << pl330->pcfg.num_chan) - 1)))) {
			pl330_error_locked(pl330, -EIO);
			ret = pl330->lifecycle_error;
		}
		stopped = !ret && (!pch->thread ||
			_state(pch->thread) == PL330_STATE_STOPPED);
		spin_unlock_irqrestore(&pl330->lock, flags);
		if (ret)
			goto out;
		if (stopped)
			break;
		if (ktime_compare(ktime_get(), deadline) >= 0) {
			spin_lock_irqsave(&pl330->lock, flags);
			pl330_error_locked(pl330, -ETIMEDOUT);
			ret = pl330->lifecycle_error;
			spin_unlock_irqrestore(&pl330->lock, flags);
			goto out;
		}
		usleep_range(50, 100);
	}

	/* Linearize proof with all producers and keep admission closed during reclaim. */
	spin_lock_irqsave(&pch->lock, flags);
	spin_lock(&pl330->lock);
	ret = pl330->lifecycle_error;
	if (!pl330_software_drained_locked(pch))
		pl330_failstop(pl330, "software users appeared behind cutoff");
	if (!ret && ((pch->thread && _state(pch->thread) != PL330_STATE_STOPPED) ||
	    (readl(pl330->base + FSM) & 1) ||
	    (readl(pl330->base + FSC) & ((1U << pl330->pcfg.num_chan) - 1)))) {
		pl330_error_locked(pl330, -EIO);
		ret = pl330->lifecycle_error;
	}
	if (!ret)
		list_splice_tail_init(&pch->retired_list, &reclaim);
	spin_unlock(&pl330->lock);
	spin_unlock_irqrestore(&pch->lock, flags);
	if (ret)
		goto out;
	list_for_each_entry_safe(desc, next, &reclaim, node) {
		list_del_init(&desc->node);
		if (refcount_read(&desc->refs) != 1)
			pl330_failstop(pl330, "retired descriptor still borrowed");
		pl330_desc_release(pl330, desc);
	}
	spin_lock_irqsave(&pch->lock, flags);
	if (pch->pm_ref_held) {
		pch->pm_ref_held = false;
		put_pm = true;
	}
	spin_unlock_irqrestore(&pch->lock, flags);
	if (put_pm) {
		pm_runtime_mark_last_busy(pl330->ddma.dev);
		pm_runtime_put_autosuspend(pl330->ddma.dev);
	}
	spin_lock_irqsave(&pch->lock, flags);
	spin_lock(&pl330->lock);
	ret = pl330->lifecycle_error;
	if (!ret) {
		pch->quiescing = false;
		if (pch->thread)
			pch->thread->accept_callbacks = true;
	}
	spin_unlock(&pl330->lock);
	spin_unlock_irqrestore(&pch->lock, flags);
out:
	mutex_unlock(&pch->sync_mutex);
	return ret;
}

static void pl330_synchronize(struct dma_chan *chan)
{
	if (pl330_synchronize_checked(chan))
		pl330_failstop(to_pchan(chan)->dmac, "void synchronize cannot transfer owner");
}

'''


def synchronization(source, header):
    anchor=function(source,"pl330_pause")
    source=replace(source,anchor,SYNC+anchor)
    source=replace(source,"\tpd->device_terminate_all = pl330_terminate_all;", "\tpd->device_terminate_all = pl330_terminate_all;\n\tpd->device_synchronize = pl330_synchronize;\n\tpd->device_synchronize_checked = pl330_synchronize_checked;")
    header=replace(header,"\tvoid (*device_synchronize)(struct dma_chan *chan);", "\tvoid (*device_synchronize)(struct dma_chan *chan);\n\t/* BSP optional: negative means software drained but allocation must be retained. */\n\tint (*device_synchronize_checked)(struct dma_chan *chan);")
    anchor=function(header,"dmaengine_synchronize")
    extra='''

/* BSP checked providers must fail-stop rather than return with live callbacks. */
static inline int dmaengine_synchronize_checked(struct dma_chan *chan)
{
	might_sleep();
	if (chan->device->device_synchronize_checked)
		return chan->device->device_synchronize_checked(chan);
	/* Other providers retain their existing void synchronization contract. */
	dmaengine_synchronize(chan);
	return 0;
}'''
    header=replace(header,anchor,anchor+extra)
    return source,header
