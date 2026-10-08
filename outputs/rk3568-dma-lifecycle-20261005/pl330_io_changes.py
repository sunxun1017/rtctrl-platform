#!/usr/bin/env python3
"""IRQ power lease and fixed-epoch pause/status users of a physical thread."""
from source_utils import function, replace

OPERATIONS = '''/* Admit before PM; checked synchronization waits through the last PM put. */
static int pl330_operation_begin(struct dma_pl330_chan *pch, u64 *epoch)
{
	unsigned long flags;
	int ret;

	spin_lock_irqsave(&pch->lock, flags);
	ret = READ_ONCE(pch->dmac->lifecycle_error);
	if (!ret && (pch->quiescing || !pch->thread))
		ret = -EIO;
	if (!ret) {
		*epoch = pch->epoch;
		atomic_inc(&pch->operations);
	}
	spin_unlock_irqrestore(&pch->lock, flags);
	return ret;
}

static void pl330_operation_end(struct dma_pl330_chan *pch)
{
	atomic_dec(&pch->operations);
	wake_up_all(&pch->drain_wait);
}

'''

IRQ = '''static irqreturn_t pl330_irq_handler(int irq, void *data)
{
	struct pl330_dmac *pl330 = data;
	irqreturn_t ret;

	/* A pending IRQ after autosuspend must not access unpowered registers. */
	if (pm_runtime_get_if_in_use(pl330->ddma.dev) <= 0)
		return IRQ_NONE;
	ret = pl330_update(pl330) ? IRQ_HANDLED : IRQ_NONE;
	pm_runtime_mark_last_busy(pl330->ddma.dev);
	pm_runtime_put_autosuspend(pl330->ddma.dev);
	return ret;
}'''

PAUSE = '''static int pl330_pause(struct dma_chan *chan)
{
	struct dma_pl330_chan *pch = to_pchan(chan);
	struct pl330_dmac *pl330 = pch->dmac;
	unsigned long flags;
	u64 epoch;
	int ret, pm_ret;

	ret = pl330_operation_begin(pch, &epoch);
	if (ret)
		return ret;
	pm_ret = pm_runtime_get_sync(pl330->ddma.dev);
	spin_lock_irqsave(&pch->lock, flags);
	spin_lock(&pl330->lock);
	if (pm_ret < 0)
		pl330_pm_error_locked(pl330, pm_ret);
	ret = pl330->lifecycle_error;
	if (!ret && (pch->quiescing || pch->epoch != epoch))
		ret = -EIO;
	if (!ret)
		ret = _stop(pch->thread);
	spin_unlock(&pl330->lock);
	spin_unlock_irqrestore(&pch->lock, flags);
	if (pm_ret < 0)
		pm_runtime_put_noidle(pl330->ddma.dev);
	else {
		pm_runtime_mark_last_busy(pl330->ddma.dev);
		pm_runtime_put_autosuspend(pl330->ddma.dev);
	}
	pl330_operation_end(pch);
	return ret;
}'''


def powered_io(source):
    source=replace(source, "\tatomic_t issuers;", "\tatomic_t issuers;\n\tatomic_t operations;")
    source=replace(source, "\t\tatomic_set(&pch->issuers, 0);", "\t\tatomic_set(&pch->issuers, 0);\n\t\tatomic_set(&pch->operations, 0);")
    source=replace(source, "\t\t!atomic_read(&pch->issuers) && !atomic_read(&pch->preparations) &&", "\t\t!atomic_read(&pch->issuers) && !atomic_read(&pch->operations) &&\n\t\t!atomic_read(&pch->preparations) &&")
    source=replace(source,function(source,"pl330_irq_handler"),IRQ)
    source=replace(source,function(source,"pl330_pause"),OPERATIONS+PAUSE)
    old=function(source,"pl330_get_current_xferred_count")
    new=replace(old,"\tstruct pl330_dmac *pl330 = pch->dmac;\n", "")
    new=replace(new,"\tpm_runtime_get_sync(pl330->ddma.dev);\n", "\t/* Caller holds controller lock and an admitted, successful PM lease. */\n")
    new=replace(new,"\tpm_runtime_mark_last_busy(pch->dmac->ddma.dev);\n\tpm_runtime_put_autosuspend(pl330->ddma.dev);\n", "")
    source=replace(source,old,new)
    old=function(source,"pl330_tx_status")
    new=replace(old,"\tunsigned int transferred, residual = 0;", "\tunsigned int transferred, residual = 0;\n\tstruct pl330_dmac *pl330 = pch->dmac;\n\tu64 epoch;\n\tint pm_ret;")
    new=replace(new,"\tret = dma_cookie_status(chan, cookie, txstate);", "\tif (READ_ONCE(pl330->lifecycle_error))\n\t\treturn DMA_ERROR;\n\tret = dma_cookie_status(chan, cookie, txstate);")
    new=replace(new,"\tspin_lock_irqsave(&pch->lock, flags);\n\tspin_lock(&pch->thread->dmac->lock);", '''	if (pl330_operation_begin(pch, &epoch))
		return DMA_ERROR;
	pm_ret = pm_runtime_get_sync(pl330->ddma.dev);
	spin_lock_irqsave(&pch->lock, flags);
	spin_lock(&pl330->lock);
	if (pm_ret < 0)
		pl330_pm_error_locked(pl330, pm_ret);
	if (pl330->lifecycle_error || pch->quiescing || pch->epoch != epoch) {
		ret = DMA_ERROR;
		goto unlock;
	}''')
    new=replace(new,"\tspin_unlock(&pch->thread->dmac->lock);\n\tspin_unlock_irqrestore(&pch->lock, flags);", '''unlock:
	spin_unlock(&pl330->lock);
	spin_unlock_irqrestore(&pch->lock, flags);
	if (pm_ret < 0)
		pm_runtime_put_noidle(pl330->ddma.dev);
	else {
		pm_runtime_mark_last_busy(pl330->ddma.dev);
		pm_runtime_put_autosuspend(pl330->ddma.dev);
	}
	pl330_operation_end(pch);''')
    source=replace(source,old,new)
    return source
