#!/usr/bin/env python3
"""Final channel release reuses process proof while keeping admission closed."""
from source_utils import function, replace

FREE = '''static void pl330_free_chan_resources(struct dma_chan *chan)
{
	struct dma_pl330_chan *pch = to_pchan(chan);
	struct pl330_dmac *pl330 = pch->dmac;
	unsigned long flags;

	/* The void DMA core path cannot transfer the client's allocation owner. */
	if (pl330_sync_channel(chan, false))
		pl330_failstop(pl330, "free channel stop proof");
	spin_lock_irqsave(&pch->lock, flags);
	if (atomic_read(&pch->prepared_descs))
		pl330_failstop(pl330, "free channel has a private prepared owner");
	spin_unlock_irqrestore(&pch->lock, flags);
	/* No new queued tasklet can pass the still-closed admission gate. */
	tasklet_kill(&pch->task);
	spin_lock_irqsave(&pch->lock, flags);
	spin_lock(&pl330->lock);
	if (pl330->lifecycle_error || !pl330_software_drained_locked(pch))
		pl330_failstop(pl330, "channel release behind cutoff");
	pl330_release_channel(pch->thread);
	pch->thread = NULL;
	spin_unlock(&pl330->lock);
	spin_unlock_irqrestore(&pch->lock, flags);
	pl330_unprep_slave_fifo(pch);
}'''

ALLOC = '''static int pl330_alloc_chan_resources(struct dma_chan *chan)
{
	struct dma_pl330_chan *pch = to_pchan(chan);
	struct pl330_dmac *pl330 = pch->dmac;
	unsigned long flags;
	int ret;

	spin_lock_irqsave(&pch->lock, flags);
	spin_lock(&pl330->lock);
	ret = pl330->lifecycle_error;
	if (!ret && pl330->state == DYING)
		ret = -ENODEV;
	if (ret)
		goto unlock;
	dma_cookie_init(chan);
	pch->thread = pl330_request_channel(pl330);
	if (!pch->thread) {
		ret = -ENOMEM;
		goto unlock;
	}
	pch->epoch++;
	pch->quiescing = false;
	pch->thread->owner_pch = pch;
	pch->thread->accept_callbacks = true;
	tasklet_setup(&pch->task, pl330_tasklet);
	ret = 1;
unlock:
	spin_unlock(&pl330->lock);
	spin_unlock_irqrestore(&pch->lock, flags);
	return ret;
}'''


def channel_release(source):
    old=function(source,"pl330_synchronize_checked")
    new=replace(old,"static int pl330_synchronize_checked(struct dma_chan *chan)", "static int pl330_sync_channel(struct dma_chan *chan, bool reopen)")
    new=replace(new,"\tif (!ret) {\n\t\tpch->quiescing = false;", "\tif (!ret && reopen) {\n\t\tpch->quiescing = false;")
    source=replace(source,old,new+'''

static int pl330_synchronize_checked(struct dma_chan *chan)
{
	return pl330_sync_channel(chan, true);
}''')
    old=function(source,"pl330_release_channel")
    new=replace(old,"\t_stop(thrd);\n", "\t/* Caller already proved STOPPED and software drain with admission closed. */\n")
    new=replace(new,"\tthrd->accept_callbacks = false;", "\tthrd->accept_callbacks = false;\n\tthrd->owner_pch = NULL;")
    source=replace(source,old,new)
    source=replace(source,function(source,"pl330_free_chan_resources"),FREE)
    source=replace(source,function(source,"pl330_alloc_chan_resources"),ALLOC)
    # A channel after free has no physical thread until a successful new allocation.
    old=function(source,"pl330_prep_begin")
    new=replace(old,"pch->quiescing || READ_ONCE(pch->dmac->lifecycle_error)", "pch->quiescing || !pch->thread || READ_ONCE(pch->dmac->lifecycle_error)")
    source=replace(source,old,new)
    return source
