static int i2s_checked_component_trigger(struct snd_soc_component *component,
					 struct snd_pcm_substream *substream,
					 int cmd)
{
	struct rk_i2s_tdm_dev *i2s_tdm = snd_soc_component_get_drvdata(component);
	unsigned long flags;
	int ret = 0;

	if (!i2s_tdm->checked_lifecycle)
		return 0;
	if (substream->stream != 0 && substream->stream != 1)
		return -EINVAL;
	if (i2s_tdm->shared_params_enabled) {
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		switch (cmd) {
		case SNDRV_PCM_TRIGGER_START:
		case SNDRV_PCM_TRIGGER_RESUME:
		case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
			ret = i2s_trcm_admit_locked(i2s_tdm, substream);
			break;
		case SNDRV_PCM_TRIGGER_STOP:
		case SNDRV_PCM_TRIGGER_SUSPEND:
		case SNDRV_PCM_TRIGGER_PAUSE_PUSH:
			ret = i2s_trcm_stop_locked(i2s_tdm, substream, true);
			break;
		default:
			ret = -EINVAL;
			break;
		}
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		return ret;
	}
	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		if (i2s_tdm->runtime_error)
			ret = i2s_tdm->runtime_error;
		else if (i2s_tdm->shutting_down)
			ret = -ESHUTDOWN;
		else if (!READ_ONCE(i2s_tdm->ready))
			ret = -EAGAIN;
		else if (i2s_tdm->configuring || i2s_tdm->power_transition || (i2s_tdm->started & ~BIT(substream->stream)) ||
			 (!i2s_tdm->started && !i2s_tdm->stop_proven))
			ret = -EBUSY;
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		break;
	default:
		break;
	}
	return ret;
}
