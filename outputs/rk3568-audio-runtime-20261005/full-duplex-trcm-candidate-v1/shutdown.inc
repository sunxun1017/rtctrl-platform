static void rockchip_i2s_tdm_shutdown(struct snd_pcm_substream *substream,
				      struct snd_soc_dai *dai)
{
	struct rk_i2s_tdm_dev *i2s_tdm = snd_soc_dai_get_drvdata(dai);
	unsigned long flags;
	int ret = 0;

	if (i2s_tdm->checked_lifecycle) {
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		if (i2s_tdm->shared_params_enabled) {
			if ((substream->stream != 0 && substream->stream != 1) ||
			    i2s_tdm->substreams[substream->stream] != substream) {
				spin_unlock_irqrestore(&i2s_tdm->lock, flags);
				return;
			}
			/* Legal ALSA close is serialized against its own trigger/GO call. */
			if (i2s_tdm->starting & BIT(substream->stream)) {
				spin_unlock_irqrestore(&i2s_tdm->lock, flags);
				i2s_checked_failstop(i2s_tdm, "close with C3 GO borrow", -EBUSY);
				return;
			}
			ret = i2s_trcm_stop_locked(i2s_tdm, substream, false);
		} else if (!(i2s_tdm->started & ~BIT(substream->stream))) {
			ret = i2s_checked_stop_locked(i2s_tdm, substream->stream, true);
		}
		if (READ_ONCE(i2s_tdm->substreams[substream->stream]) == substream)
			WRITE_ONCE(i2s_tdm->substreams[substream->stream], NULL);
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		if (i2s_tdm->irq > 0)
			synchronize_irq(i2s_tdm->irq);
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		if (!READ_ONCE(i2s_tdm->substreams[0]) && !READ_ONCE(i2s_tdm->substreams[1]) && !i2s_tdm->starting)
			i2s_tdm->irq_drained = true;
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		if (!ret && i2s_tdm->shared_params_enabled)
			ret = i2s_shared_free(substream, dai);
		if (ret)
			dev_err(i2s_tdm->dev, "CPU shutdown stop unproved: %d\n", ret);
		return;
	}
	i2s_tdm->substreams[substream->stream] = NULL;
}
