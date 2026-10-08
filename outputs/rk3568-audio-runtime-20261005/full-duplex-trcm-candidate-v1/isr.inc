static irqreturn_t i2s_trcm_isr(struct rk_i2s_tdm_dev *i2s_tdm)
{
	struct snd_pcm_substream *playback = NULL, *capture = NULL;
	unsigned long flags;
	unsigned int val = 0, owners;
	int ret;
	irqreturn_t result = IRQ_NONE;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (!i2s_tdm->irq_live || i2s_tdm->shutting_down)
		goto unlock;
	ret = regmap_read(i2s_tdm->regmap, I2S_INTSR, &val);
	if (!ret && !(val & (I2S_INTSR_TXUI_ACT | I2S_INTSR_RXOI_ACT)))
		goto unlock;
	owners = i2s_tdm->started | i2s_tdm->starting;
	if (!ret && (val & I2S_INTSR_TXUI_ACT)) {
		ret = i2s_checked_irq_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, false);
		if (owners & BIT(SNDRV_PCM_STREAM_PLAYBACK))
			playback = READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_PLAYBACK]);
		result = IRQ_HANDLED;
	}
	if (!ret && (val & I2S_INTSR_RXOI_ACT)) {
		ret = i2s_checked_irq_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, false);
		if (owners & BIT(SNDRV_PCM_STREAM_CAPTURE))
			capture = READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_CAPTURE]);
		result = IRQ_HANDLED;
	}
	if (ret) {
		/* A failed status read never interprets val. Failed shared IO affects both. */
		if (owners & BIT(SNDRV_PCM_STREAM_PLAYBACK))
			playback = READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_PLAYBACK]);
		if (owners & BIT(SNDRV_PCM_STREAM_CAPTURE))
			capture = READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_CAPTURE]);
		i2s_trcm_joint_locked(i2s_tdm, ret);
		result = IRQ_HANDLED;
	}
unlock:
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	/* Native START holds its stream lock through RUNNING publication. XRUN waits
	 * outside the CPU lock; close synchronize_irq drains captured pointer borrows.
	 */
	if (playback)
		snd_pcm_stop_xrun(playback);
	if (capture)
		snd_pcm_stop_xrun(capture);
	return result;
}
