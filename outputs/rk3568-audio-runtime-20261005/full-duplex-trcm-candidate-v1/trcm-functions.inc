/* All transport/ticket state below is protected by the CPU lock. */
static int i2s_trcm_joint_locked(struct rk_i2s_tdm_dev *i2s_tdm, int first)
{
	int ret, next;

	if (first < 0)
		i2s_checked_error_locked(i2s_tdm, first);
	/* Revoke admission, but an in-flight C3 GO borrow survives until its STOP. */
	i2s_tdm->starting_valid = 0;
	ret = i2s_checked_dma_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, false);
	next = i2s_checked_dma_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, false);
	ret = i2s_checked_first_error(ret, next);
	next = regmap_write_bits(i2s_tdm->regmap, I2S_XFER,
		I2S_XFER_TXS_MASK | I2S_XFER_RXS_MASK,
		I2S_XFER_TXS_STOP | I2S_XFER_RXS_STOP);
	ret = i2s_checked_first_error(ret, next);
	udelay(150);
	next = i2s_checked_clear_locked(i2s_tdm);
	ret = i2s_checked_first_error(ret, next);
	if (!ret) {
		i2s_tdm->stop_reads++;
		if ((readl(i2s_tdm->regs + I2S_XFER) & (I2S_XFER_TXS_MASK | I2S_XFER_RXS_MASK)) ||
		    (readl(i2s_tdm->regs + I2S_DMACR) & (I2S_DMACR_TDE_MASK | I2S_DMACR_RDE_MASK)) ||
		    (readl(i2s_tdm->regs + I2S_INTCR) & (I2S_INTCR_TXUIE_MASK | I2S_INTCR_RXOIE_MASK)))
			ret = -EIO;
	}
	if (!ret) {
		i2s_tdm->started = 0;
		i2s_tdm->trcm_active[0] = i2s_tdm->trcm_active[1] = NULL;
		i2s_tdm->transport_live = false;
		i2s_tdm->quiet_proven = BIT(0) | BIT(1);
	} else {
		i2s_tdm->quiet_proven = 0;
	}
	i2s_tdm->stop_proven = !ret && !i2s_tdm->starting;
	i2s_checked_error_locked(i2s_tdm, ret);
	return i2s_checked_first_error(first, ret);
}

static int i2s_checked_all_stop_locked(struct rk_i2s_tdm_dev *i2s_tdm)
{
	int ret, next;

	if (i2s_tdm->shared_params_enabled)
		return i2s_trcm_joint_locked(i2s_tdm, 0);
	ret = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_PLAYBACK, true);
	next = i2s_checked_stop_locked(i2s_tdm, SNDRV_PCM_STREAM_CAPTURE, true);
	return i2s_checked_first_error(ret, next);
}

static int i2s_trcm_quiet_locked(struct rk_i2s_tdm_dev *i2s_tdm, int stream)
{
	unsigned int dmask = stream == SNDRV_PCM_STREAM_PLAYBACK ?
		I2S_DMACR_TDE_MASK : I2S_DMACR_RDE_MASK;
	unsigned int imask = stream == SNDRV_PCM_STREAM_PLAYBACK ?
		I2S_INTCR_TXUIE_MASK : I2S_INTCR_RXOIE_MASK;
	int ret = i2s_checked_dma_locked(i2s_tdm, stream, false);

	if (!ret && ((readl(i2s_tdm->regs + I2S_DMACR) & dmask) ||
		     (readl(i2s_tdm->regs + I2S_INTCR) & imask)))
		ret = -EIO;
	if (!ret)
		i2s_tdm->quiet_proven |= BIT(stream);
	else
		i2s_tdm->quiet_proven &= ~BIT(stream);
	return ret;
}

static int i2s_trcm_admit_locked(struct rk_i2s_tdm_dev *i2s_tdm,
			       struct snd_pcm_substream *ss)
{
	unsigned int bit;
	int stream = ss->stream;

	if (stream != SNDRV_PCM_STREAM_PLAYBACK && stream != SNDRV_PCM_STREAM_CAPTURE)
		return -EINVAL;
	bit = BIT(stream);
	if (i2s_tdm->runtime_error)
		return i2s_tdm->runtime_error;
	if (i2s_tdm->shutting_down)
		return -ESHUTDOWN;
	if (!READ_ONCE(i2s_tdm->ready))
		return -EAGAIN;
	if (i2s_tdm->configuring || i2s_tdm->power_transition || i2s_tdm->shared_params.pending ||
	    ((i2s_tdm->started | i2s_tdm->starting) & bit))
		return -EBUSY;
	if (i2s_tdm->substreams[stream] != ss || i2s_tdm->shared_params.owner[stream] != ss ||
	    !(i2s_tdm->shared_prepared & bit))
		return -EINVAL;
	if (!i2s_tdm->transport_live && !i2s_tdm->stop_proven)
		return -EBUSY;
	if (!i2s_tdm->trcm_epoch)
		i2s_tdm->trcm_epoch = 1;
	i2s_tdm->trcm_ticket[stream] = ss;
	i2s_tdm->trcm_ticket_epoch[stream] = i2s_tdm->trcm_epoch;
	i2s_tdm->starting |= bit;
	i2s_tdm->starting_valid |= bit;
	i2s_tdm->irq_drained = false;
	return 0;
}

static int i2s_trcm_commit_locked(struct rk_i2s_tdm_dev *i2s_tdm,
				struct snd_pcm_substream *ss)
{
	unsigned int bit = BIT(ss->stream);
	bool first;
	int ret;

	if (i2s_tdm->runtime_error)
		return i2s_tdm->runtime_error;
	if (i2s_tdm->shutting_down)
		return -ESHUTDOWN;
	if (!READ_ONCE(i2s_tdm->ready))
		return -EAGAIN;
	if (i2s_tdm->configuring || i2s_tdm->power_transition || i2s_tdm->shared_params.pending)
		return -EBUSY;
	if (!(i2s_tdm->starting & i2s_tdm->starting_valid & bit) ||
	    i2s_tdm->trcm_ticket[ss->stream] != ss ||
	    i2s_tdm->trcm_ticket_epoch[ss->stream] != i2s_tdm->trcm_epoch ||
	    i2s_tdm->substreams[ss->stream] != ss ||
	    i2s_tdm->shared_params.owner[ss->stream] != ss ||
	    !(i2s_tdm->shared_prepared & bit))
		return -EINVAL;
	first = !i2s_tdm->transport_live;
	if (first && !i2s_tdm->stop_proven)
		return -EBUSY;
	i2s_tdm->stop_proven = false;
	i2s_tdm->quiet_proven &= ~bit;
	/* Own access before the first request write may partly execute. */
	i2s_tdm->transport_live = true;
	ret = i2s_checked_dma_locked(i2s_tdm, ss->stream, true);
	if (!ret && first)
		ret = regmap_write_bits(i2s_tdm->regmap, I2S_XFER,
			I2S_XFER_TXS_MASK | I2S_XFER_RXS_MASK,
			I2S_XFER_TXS_START | I2S_XFER_RXS_START);
	if (ret) {
		i2s_trcm_joint_locked(i2s_tdm, ret);
		return ret;
	}
	i2s_tdm->started |= bit;
	i2s_tdm->trcm_active[ss->stream] = ss;
	i2s_tdm->starting &= ~bit;
	i2s_tdm->starting_valid &= ~bit;
	i2s_tdm->trcm_ticket[ss->stream] = NULL;
	i2s_tdm->trcm_ticket_epoch[ss->stream] = 0;
	return 0;
}

static int i2s_trcm_stop_locked(struct rk_i2s_tdm_dev *i2s_tdm,
			      struct snd_pcm_substream *ss, bool component)
{
	unsigned int bit = BIT(ss->stream);
	bool ticket = (i2s_tdm->starting & bit) && i2s_tdm->trcm_ticket[ss->stream] == ss;
	bool active = (i2s_tdm->started & bit) && i2s_tdm->trcm_active[ss->stream] == ss;
	int ret;

	/* Component rollback owns only its published ticket; failed admission may own nothing. */
	if (component && !ticket)
		return 0;
	if (!ticket && !active)
		return 0;
	if (i2s_tdm->substreams[ss->stream] != ss)
		return -EINVAL;
	i2s_tdm->starting_valid &= ~bit;
	ret = i2s_trcm_quiet_locked(i2s_tdm, ss->stream);
	if (ret)
		i2s_trcm_joint_locked(i2s_tdm, ret);
	if (!ret) {
		i2s_tdm->started &= ~bit;
		i2s_tdm->trcm_active[ss->stream] = NULL;
	}
	if (component && ticket) {
		/* C3 rollback has returned from its GO callback; same-ss ALSA is serialized. */
		i2s_tdm->starting &= ~bit;
		i2s_tdm->trcm_ticket[ss->stream] = NULL;
		i2s_tdm->trcm_ticket_epoch[ss->stream] = 0;
	}
	if (!(i2s_tdm->started | i2s_tdm->starting)) {
		int next = i2s_trcm_joint_locked(i2s_tdm, 0);
		ret = i2s_checked_first_error(ret, next);
	} else {
		i2s_tdm->stop_proven = false;
	}
	return ret;
}

static int i2s_trcm_trigger(struct rk_i2s_tdm_dev *i2s_tdm,
			  struct snd_pcm_substream *ss, int cmd)
{
	unsigned long flags;
	int ret;

	if (ss->stream != SNDRV_PCM_STREAM_PLAYBACK && ss->stream != SNDRV_PCM_STREAM_CAPTURE)
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	switch (cmd) {
	case SNDRV_PCM_TRIGGER_START:
	case SNDRV_PCM_TRIGGER_RESUME:
	case SNDRV_PCM_TRIGGER_PAUSE_RELEASE:
		ret = i2s_trcm_commit_locked(i2s_tdm, ss);
		break;
	case SNDRV_PCM_TRIGGER_STOP:
	case SNDRV_PCM_TRIGGER_SUSPEND:
	case SNDRV_PCM_TRIGGER_PAUSE_PUSH:
		ret = i2s_trcm_stop_locked(i2s_tdm, ss, false);
		break;
	default:
		ret = -EINVAL;
		break;
	}
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}
