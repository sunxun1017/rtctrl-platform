"""CPU IRQ publication/revocation plus component and DAI admission."""
from source_utils import replace


GATES = r'''
static int i2s_checked_prepare(struct snd_pcm_substream *substream,
			       struct snd_soc_dai *dai)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	unsigned long flags;
	int ret;

	if (!i2s_tdm->checked_lifecycle)
		return 0;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	ret = i2s_checked_gate_locked(i2s_tdm);
	if (!ret)
		ret = i2s_checked_stop_locked(i2s_tdm, substream->stream, true);
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static int i2s_checked_component_trigger(struct snd_soc_component *component,
					 struct snd_pcm_substream *substream,
					 int cmd)
{
	struct rk_i2s_tdm_dev *i2s_tdm = snd_soc_component_get_drvdata(component);
	unsigned long flags;
	int ret = 0;

	if (!i2s_tdm->checked_lifecycle)
		return 0;
	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		if (i2s_tdm->runtime_error)
			ret = i2s_tdm->runtime_error;
		else if (i2s_tdm->shutting_down)
			ret = -ESHUTDOWN;
		else if (i2s_tdm->configuring || (i2s_tdm->started & ~BIT(substream->stream)))
			ret = -EBUSY;
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		break;
	default:
		/* STOP must reach generic DMA cleanup even when CPU is poisoned. */
		break;
	}
	return ret;
}
'''

ISR = r'''
static irqreturn_t i2s_checked_isr(struct rk_i2s_tdm_dev *i2s_tdm)
{
	struct snd_pcm_substream *playback = NULL, *capture = NULL;
	unsigned long flags;
	unsigned int val = 0;
	int ret;
	irqreturn_t result = IRQ_NONE;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (!i2s_tdm->irq_live || i2s_tdm->shutting_down)
		goto unlock;
	ret = regmap_read(i2s_tdm->regmap, I2S_INTSR, &val);
	if (ret) {
		i2s_checked_error_locked(i2s_tdm, ret);
		/* Do not interpret failed INTSR. Notify only the known active owner. */
		if (i2s_tdm->started & BIT(SNDRV_PCM_STREAM_PLAYBACK))
			playback = READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_PLAYBACK]);
		if (i2s_tdm->started & BIT(SNDRV_PCM_STREAM_CAPTURE))
			capture = READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_CAPTURE]);
		i2s_checked_irq_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, false);
		i2s_checked_irq_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, false);
		result = IRQ_HANDLED;
		goto unlock;
	}
	if (val & I2S_INTSR_TXUI_ACT) {
		ret = i2s_checked_irq_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, false);
		i2s_checked_error_locked(i2s_tdm, ret);
		if (i2s_tdm->started & BIT(SNDRV_PCM_STREAM_PLAYBACK))
			playback = READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_PLAYBACK]);
		result = IRQ_HANDLED;
	}
	if (val & I2S_INTSR_RXOI_ACT) {
		ret = i2s_checked_irq_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, false);
		i2s_checked_error_locked(i2s_tdm, ret);
		if (i2s_tdm->started & BIT(SNDRV_PCM_STREAM_CAPTURE))
			capture = READ_ONCE(i2s_tdm->substreams[SNDRV_PCM_STREAM_CAPTURE]);
		result = IRQ_HANDLED;
	}
unlock:
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	/* ALSA takes stream locks then I2S lock. Never reverse this order. */
	if (playback)
		snd_pcm_stop_xrun(playback);
	if (capture)
		snd_pcm_stop_xrun(capture);
	return result;
}
'''


def irq_lifecycle(source):
    source = replace(source, "\tbool stop_proven;", "\tbool stop_proven;\n\tbool irq_live;\n\tbool mclks_enabled;\n\tint irq;")
    source = replace(source, "static int rockchip_i2s_tdm_startup(", GATES + "\nstatic int rockchip_i2s_tdm_startup(")
    old = "\tint stream = substream->stream;\n\n\tif (i2s_tdm->substreams[stream])"
    new = r'''	int stream = substream->stream;
	unsigned long flags;
	int ret;

	if (i2s_tdm->checked_lifecycle) {
		if (stream != SNDRV_PCM_STREAM_PLAYBACK && stream != SNDRV_PCM_STREAM_CAPTURE)
			return -EINVAL;
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		ret = i2s_checked_gate_locked(i2s_tdm);
		if (!ret && READ_ONCE(i2s_tdm->substreams[stream]))
			ret = -EBUSY;
		if (!ret) {
			if (i2s_tdm->wait_time[stream])
				substream->wait_time = msecs_to_jiffies(i2s_tdm->wait_time[stream]);
			WRITE_ONCE(i2s_tdm->substreams[stream], substream);
		}
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		return ret;
	}

	if (i2s_tdm->substreams[stream])'''
    source = replace(source, old, new)
    source = replace(source, "\ti2s_tdm->substreams[substream->stream] = NULL;", r'''	unsigned long flags;
	int ret = 0;

	if (i2s_tdm->checked_lifecycle) {
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		if (READ_ONCE(i2s_tdm->substreams[substream->stream]) == substream)
			WRITE_ONCE(i2s_tdm->substreams[substream->stream], NULL);
		if (!(i2s_tdm->started & ~BIT(substream->stream)))
			ret = i2s_checked_stop_locked(i2s_tdm, substream->stream, true);
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		/* Process context, outside stream/I2S locks; covers captured old pointer. */
		if (i2s_tdm->irq > 0)
			synchronize_irq(i2s_tdm->irq);
		if (ret)
			dev_err(i2s_tdm->dev, "CPU shutdown stop unproved: %d\n", ret);
		/* Sticky faults retain the device/clocks; checked PM refuses suspension. */
		return;
	}
	i2s_tdm->substreams[substream->stream] = NULL;''')
    source = replace(source, "\t.shutdown = rockchip_i2s_tdm_shutdown,", "\t.shutdown = rockchip_i2s_tdm_shutdown,\n\t.prepare = i2s_checked_prepare,")
    source = replace(source, "\t.name = DRV_NAME,\n\t.controls", "\t.name = DRV_NAME,\n\t.trigger = i2s_checked_component_trigger,\n\t.controls")
    source = replace(source, "static irqreturn_t rockchip_i2s_tdm_isr(", ISR + "\nstatic irqreturn_t rockchip_i2s_tdm_isr(")
    source = replace(source, "\tu32 val;\n\n\tregmap_read(i2s_tdm->regmap, I2S_INTSR, &val);", "\tu32 val;\n\n\tif (i2s_tdm->checked_lifecycle)\n\t\treturn i2s_checked_isr(i2s_tdm);\n\n\tregmap_read(i2s_tdm->regmap, I2S_INTSR, &val);")
    return source
