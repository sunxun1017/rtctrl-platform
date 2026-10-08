/* Called from atomic contexts. The binding is immutable from open to drain. */
static void dmaengine_pcm_notify_fault(struct snd_pcm_substream *substream,
				      int error, bool stop_xrun)
{
	struct dmaengine_pcm_runtime_data *prtd = substream_to_prtd(substream);
	void (*sink)(struct snd_pcm_substream *, int, void *);
	void *sink_arg;
	unsigned long flags;

	if (!prtd || !prtd->checked)
		return;
	error = dmaengine_pcm_error(prtd, error < 0 ? error : -EIO);
	spin_lock_irqsave(&prtd->lifecycle_lock, flags);
	sink = prtd->error_sink;
	sink_arg = prtd->error_sink_arg;
	spin_unlock_irqrestore(&prtd->lifecycle_lock, flags);
	/* CPU admission/ticket failure precedes the ALSA state action. */
	if (sink)
		sink(substream, error, sink_arg);
	/* Synchronous trigger/pointer callers may already own the stream lock. */
	if (stop_xrun)
		snd_pcm_stop_xrun(substream);
}

static int dmaengine_pcm_check_fault(struct snd_pcm_substream *substream)
{
	struct dmaengine_pcm_runtime_data *prtd = substream_to_prtd(substream);
	int error;

	if (!prtd || !prtd->checked)
		return 0;
	/* This accessor is cached, IRQ-safe and does not acquire PM or perform I/O. */
	error = dmaengine_check_open(prtd->dma_chan);
	if (error < 0) {
		dmaengine_pcm_notify_fault(substream, error, false);
		return dmaengine_pcm_error(prtd, error);
	}
	return dmaengine_pcm_error(prtd, 0);
}

static void dmaengine_pcm_dma_complete_result(void *arg,
					    const struct dmaengine_result *result)
{
	struct snd_pcm_substream *substream = arg;
	struct dmaengine_pcm_runtime_data *prtd = substream_to_prtd(substream);
	int error;

	if (!prtd || !prtd->checked)
		return;
	error = dmaengine_check_open(prtd->dma_chan);
	if (error < 0 || (result && result->result != DMA_TRANS_NOERROR)) {
		/* Preserve exact controller errno before the result-only -EIO fallback. */
		dmaengine_pcm_notify_fault(substream, error < 0 ? error : -EIO, true);
		return;
	}
	if (dmaengine_pcm_error(prtd, 0))
		return;
	dmaengine_pcm_dma_complete(arg);
}

int snd_dmaengine_pcm_set_error_sink(struct snd_pcm_substream *substream,
		void (*sink)(struct snd_pcm_substream *, int, void *), void *arg)
{
	struct dmaengine_pcm_runtime_data *prtd = substream_to_prtd(substream);
	unsigned long flags;
	int ret = 0;

	if (!prtd || !prtd->checked)
		return sink ? -EOPNOTSUPP : 0;
	spin_lock_irqsave(&prtd->lifecycle_lock, flags);
	if (prtd->exposed || prtd->closing || prtd->quiescing || prtd->error_sink)
		ret = -EBUSY;
	else {
		prtd->error_sink = sink;
		prtd->error_sink_arg = arg;
	}
	spin_unlock_irqrestore(&prtd->lifecycle_lock, flags);
	return ret;
}
EXPORT_SYMBOL_GPL(snd_dmaengine_pcm_set_error_sink);
