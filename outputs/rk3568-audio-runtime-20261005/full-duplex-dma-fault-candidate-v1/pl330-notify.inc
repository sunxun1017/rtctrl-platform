/* PL330 has at most eight physical channel threads (CR0.num_chan is 3 bits). */
#define PL330_MAX_FAULT_CALLBACKS 8

struct pl330_fault_callback {
	struct dma_pl330_desc *desc;
	struct dmaengine_desc_callback callback;
};

/* Both pch and controller locks held; no callback is invoked here. */
static bool pl330_fault_capture_locked(struct dma_pl330_chan *pch,
				      struct pl330_fault_callback *borrow)
{
	struct dma_pl330_desc *desc;
	struct list_head *head;
	int i;

	if (!pch->dmac->lifecycle_error || pch->quiescing || !pch->thread ||
	    (pch->fault_notified && pch->fault_notified_epoch == pch->epoch))
		return false;
	for (i = 0; i < 2; i++) {
		head = i ? &pch->submitted_list : &pch->work_list;
		list_for_each_entry(desc, head, node) {
			if (desc->owner_pch != pch || desc->owner_epoch != pch->epoch ||
			    !desc->txd.callback_result)
				continue;
			borrow->desc = pl330_desc_get(desc);
			if (!borrow->desc)
				continue;
			dmaengine_desc_get_callback(&desc->txd, &borrow->callback);
			pch->fault_notified = true;
			pch->fault_notified_epoch = pch->epoch;
			return true;
		}
	}
	return false;
}

static void pl330_fault_notify(struct pl330_dmac *pl330)
{
	struct pl330_fault_callback borrowed[PL330_MAX_FAULT_CALLBACKS];
	struct dmaengine_result result = { .result = DMA_TRANS_ABORTED, .residue = 0 };
	struct dma_pl330_chan *pch;
	unsigned long flags;
	unsigned int i, count = 0;

	/* Capture every borrower before the first sink can jointly STOP peers. */
	for (i = 0; i < pl330->num_peripherals && count < ARRAY_SIZE(borrowed); i++) {
		pch = &pl330->peripherals[i];
		spin_lock_irqsave(&pch->lock, flags);
		spin_lock(&pl330->lock);
		if (pl330_fault_capture_locked(pch, &borrowed[count]))
			count++;
		spin_unlock(&pl330->lock);
		spin_unlock_irqrestore(&pch->lock, flags);
	}
	for (i = 0; i < count; i++) {
		/* Do not read descriptor fields after cutoff; use the borrowed snapshot. */
		dmaengine_desc_callback_invoke(&borrowed[i].callback, &result);
		pl330_desc_put(borrowed[i].desc);
	}
}
