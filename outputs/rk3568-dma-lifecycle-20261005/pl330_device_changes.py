#!/usr/bin/env python3
"""Terminal remove proof and conservative no-allocation system-sleep boundary."""
from source_utils import function,replace

PROOF='''/* Global cutoff is used only for final removal or no-client system sleep. */
static bool pl330_controller_drained(struct pl330_dmac *pl330)
{
	unsigned long flags;
	bool drained;

	spin_lock_irqsave(&pl330->lock, flags);
	drained = !atomic_read(&pl330->producers) &&
		!atomic_read(&pl330->irq_users) && !pl330->fault_tasklet_queued;
	spin_unlock_irqrestore(&pl330->lock, flags);
	return drained;
}

/* Caller holds a successful temporary PM lease; every admission is closed. */
static int pl330_controller_stop_proof(struct pl330_dmac *pl330)
{
	unsigned long flags;
	struct pl330_thread *thread;
	int i, ret;

	spin_lock_irqsave(&pl330->lock, flags);
	ret = pl330->lifecycle_error;
	if (ret)
		goto out;
	if ((readl(pl330->base + FSM) & 1) ||
	    (readl(pl330->base + FSC) & ((1U << pl330->pcfg.num_chan) - 1))) {
		pl330_error_locked(pl330, -EIO);
		ret = pl330->lifecycle_error;
		goto out;
	}
	writel(0, pl330->base + INTEN);
	writel(pl330->pcfg.num_events == 32 ? ~0U :
		(1U << pl330->pcfg.num_events) - 1, pl330->base + INTCLR);
	/* Manager included: channel-only proof cannot authorize freeing its mcode. */
	for (i = 0; i <= pl330->pcfg.num_chan; i++) {
		thread = i == pl330->pcfg.num_chan ? pl330->manager : &pl330->channels[i];
		if (_state(thread) != PL330_STATE_STOPPED) {
			ret = _stop(thread);
			if (!ret)
				ret = pl330_wait_state(thread, PL330_STATE_STOPPED, 20);
			if (ret)
				goto out;
		}
	}
out:
	spin_unlock_irqrestore(&pl330->lock, flags);
	return ret;
}

'''

REMOVE='''static void pl330_remove(struct amba_device *adev)
{
	struct pl330_dmac *pl330 = amba_get_drvdata(adev);
	struct dma_pl330_chan *pch, *next;
	unsigned long flags;
	int i, ret;

	/* Same core mutex as every client acquisition: no zero-snapshot race. */
	if (dmaengine_device_quiesce(&pl330->ddma))
		pl330_failstop(pl330, "remove has a live core client owner");
	ret = pm_runtime_get_sync(pl330->ddma.dev);
	if (ret < 0) {
		spin_lock_irqsave(&pl330->lock, flags);
		pl330_pm_error_locked(pl330, ret);
		spin_unlock_irqrestore(&pl330->lock, flags);
		pm_runtime_put_noidle(pl330->ddma.dev);
		pl330_failstop(pl330, "remove cannot power hardware for stop proof");
	}
	spin_lock_irqsave(&pl330->lock, flags);
	pl330->removing = true;
	pl330->state = DYING;
	for (i = 0; i < pl330->pcfg.num_chan; i++)
		pl330->channels[i].accept_callbacks = false;
	spin_unlock_irqrestore(&pl330->lock, flags);
	list_for_each_entry(pch, &pl330->ddma.channels, chan.device_node) {
		if (pch->thread)
			pl330_free_chan_resources(&pch->chan);
		else if (atomic_read(&pch->prepared_descs) || !pl330_software_drained(pch))
			pl330_failstop(pl330, "remove has software owner without physical channel");
	}
	if (!wait_event_timeout(pl330->drain_wait, pl330_controller_drained(pl330),
				msecs_to_jiffies(500)))
		pl330_failstop(pl330, "remove controller software deadline");
	if (pl330_controller_stop_proof(pl330))
		pl330_failstop(pl330, "remove manager or channel stop proof");
	/* Join API wrappers only after their counted work has met the deadline. */
	for (i = 0; i < AMBA_NR_IRQS; i++)
		if (adev->irq[i])
			devm_free_irq(&adev->dev, adev->irq[i], pl330);
	tasklet_kill(&pl330->tasks);
	if (adev->dev.of_node)
		of_dma_controller_free(adev->dev.of_node);
	dma_async_device_unregister(&pl330->ddma);
	list_for_each_entry_safe(pch, next, &pl330->ddma.channels, chan.device_node)
		list_del(&pch->chan.device_node);
	pl330_del(pl330);
	/* Successful proof allows release of the final temporary controller lease. */
	pm_runtime_put_noidle(pl330->ddma.dev);
	if (pl330->rstc_ocp)
		reset_control_assert(pl330->rstc_ocp);
	if (pl330->rstc)
		reset_control_assert(pl330->rstc);
}'''

SUSPEND='''static int __maybe_unused pl330_suspend(struct device *dev)
{
	struct amba_device *adev = to_amba_device(dev);
	struct pl330_dmac *pl330 = amba_get_drvdata(adev);
	struct dma_pl330_chan *pch;
	unsigned long flags;
	int ret;

	/* This BSP stage supports system sleep only after all DMA clients release. */
	spin_lock_irqsave(&pl330->lock, flags);
	ret = pl330->lifecycle_error;
	if (!ret)
		pl330->system_suspended = true;
	spin_unlock_irqrestore(&pl330->lock, flags);
	if (ret)
		return ret;
	list_for_each_entry(pch, &pl330->ddma.channels, chan.device_node) {
		spin_lock_irqsave(&pch->lock, flags);
		if (pch->thread || atomic_read(&pch->prepared_descs) ||
		    !pl330_software_drained_locked(pch))
			ret = -EBUSY;
		spin_unlock_irqrestore(&pch->lock, flags);
		if (ret)
			goto busy;
	}
	ret = pm_runtime_get_sync(dev);
	if (ret < 0) {
		pm_runtime_put_noidle(dev);
		goto fault;
	}
	if (!wait_event_timeout(pl330->drain_wait, pl330_controller_drained(pl330),
				msecs_to_jiffies(500)))
		pl330_failstop(pl330, "suspend controller software deadline");
	ret = pl330_controller_stop_proof(pl330);
	if (ret)
		goto fault;
	ret = pm_runtime_force_suspend(dev);
	if (ret)
		goto fault;
	pm_runtime_put_noidle(dev);
	amba_pclk_unprepare(adev);
	return 0;
busy:
	spin_lock_irqsave(&pl330->lock, flags);
	pl330->system_suspended = false;
	spin_unlock_irqrestore(&pl330->lock, flags);
	return ret;
fault:
	spin_lock_irqsave(&pl330->lock, flags);
	pl330_pm_error_locked(pl330, ret);
	ret = pl330->lifecycle_error;
	spin_unlock_irqrestore(&pl330->lock, flags);
	/* On an unknown power/stop outcome preserve the acquired PM reference. */
	return ret;
}'''

RESUME='''static int __maybe_unused pl330_resume(struct device *dev)
{
	struct amba_device *adev = to_amba_device(dev);
	struct pl330_dmac *pl330 = amba_get_drvdata(adev);
	unsigned long flags;
	int ret;

	ret = READ_ONCE(pl330->lifecycle_error);
	if (ret)
		return ret;
	ret = amba_pclk_prepare(adev);
	if (ret)
		return ret;
	ret = pm_runtime_force_resume(dev);
	if (ret) {
		amba_pclk_unprepare(adev);
		spin_lock_irqsave(&pl330->lock, flags);
		pl330_pm_error_locked(pl330, ret);
		ret = pl330->lifecycle_error;
		spin_unlock_irqrestore(&pl330->lock, flags);
		return ret;
	}
	spin_lock_irqsave(&pl330->lock, flags);
	ret = pl330->lifecycle_error;
	if (!ret)
		pl330->system_suspended = false;
	spin_unlock_irqrestore(&pl330->lock, flags);
	return ret;
}'''


def device_release(source):
    source=replace(source,"\tbool pm_failed;", "\tbool pm_failed;\n\tbool removing;\n\tbool system_suspended;\n\tbool fault_tasklet_queued;\n\tatomic_t irq_users;")
    # The IRQ ticket includes the successful PM lease's final put.
    old=function(source,"pl330_irq_handler")
    new=replace(old,"\tirqreturn_t ret;", "\tirqreturn_t ret = IRQ_NONE;")
    new=replace(new,"\t/* A pending IRQ", "\tatomic_inc(&pl330->irq_users);\n\tif (READ_ONCE(pl330->removing) || READ_ONCE(pl330->system_suspended))\n\t\tgoto out;\n\t/* A pending IRQ")
    new=replace(new,"\t\treturn IRQ_NONE;", "\t\tgoto out;")
    new=replace(new,"\treturn ret;", "out:\n\tatomic_dec(&pl330->irq_users);\n\twake_up_all(&pl330->drain_wait);\n\treturn ret;")
    source=replace(source,old,new)
    old=function(source,"pl330_update")
    new=replace(old,"\tif (pl330->pm_failed)\n", "\tif (pl330->pm_failed || pl330->removing || pl330->system_suspended)\n")
    new=replace(new,"\t\ttasklet_schedule(&pl330->tasks);", "\t\tpl330->fault_tasklet_queued = true;\n\t\ttasklet_schedule(&pl330->tasks);")
    new=replace(new,"\t\t\tid = pl330->events[ev];", "\t\t\tid = pl330->events[ev];\n\t\t\t/* A masked old event can coexist with another channel's IRQ. */\n\t\t\tif (id < 0 || id >= pl330->pcfg.num_chan)\n\t\t\t\tcontinue;")
    # Scheduling and its queued ticket remain inside the existing controller-locked if.
    source=replace(source,old,new)
    old=function(source,"pl330_dotask")
    new=replace(old,"\tif (pl330->pm_failed) {", "\tpl330->fault_tasklet_queued = false;\n\tif (pl330->pm_failed || pl330->removing || pl330->system_suspended) {")
    new=replace(new,"\t\tif (pl330->pm_failed)\n", "\t\tif (pl330->pm_failed || pl330->removing || pl330->system_suspended)\n")
    source=replace(source,old,new)
    old=function(source,"pl330_alloc_chan_resources")
    new=replace(old,"\tif (!ret && pl330->state == DYING)", "\tif (!ret && pl330->system_suspended)\n\t\tret = -EBUSY;\n\tif (!ret && (pl330->removing || pl330->state == DYING))")
    source=replace(source,old,new)
    source=replace(source,function(source,"pl330_remove"),PROOF+REMOVE)
    source=replace(source,function(source,"pl330_suspend"),SUSPEND)
    source=replace(source,function(source,"pl330_resume"),RESUME)
    return source
