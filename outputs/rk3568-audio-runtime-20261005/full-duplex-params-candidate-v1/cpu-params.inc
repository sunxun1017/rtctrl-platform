static int i2s_shared_begin(struct snd_pcm_substream *ss,
		struct snd_pcm_hw_params *params, struct snd_soc_dai *dai, u64 *cookie)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	struct snd_soc_dai_params_state *p = &i2s_tdm->shared_params;
	unsigned long flags;
	int ret;

	/* Pure finite profile rejection precedes even endpoint admission. */
	if (!i2s_tdm->shared_params_enabled || !i2s_tdm->checked_lifecycle ||
	    (ss->stream != 0 && ss->stream != 1) || params_rate(params) != 48000 ||
	    params_channels(params) != 2 || params_format(params) != SNDRV_PCM_FORMAT_S16_LE ||
	    !i2s_tdm->is_master_mode || i2s_tdm->clk_trcm != I2S_CKR_TRCM_TXONLY ||
	    i2s_tdm->bclk_fs != 64 || i2s_tdm->lrck_ratio != 1 || i2s_tdm->tdm_mode ||
	    i2s_tdm->mclk_calibrate || i2s_tdm->io_multiplex)
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	ret = i2s_checked_gate_locked(i2s_tdm);
	if (!ret && (i2s_tdm->shared_dai_fmt != (SND_SOC_DAIFMT_CBS_CFS |
		SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S) ||
		!i2s_tdm->ready || i2s_tdm->substreams[ss->stream] != ss))
		ret = -EINVAL;
	if (!ret)
		ret = snd_soc_dai_params_begin_locked(p, dai, ss, cookie);
	if (!ret) {
		p->old_clock[0] = i2s_tdm->mclk_tx_freq;
		p->old_clock[1] = i2s_tdm->mclk_rx_freq;
		i2s_tdm->configuring = true;
	}
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static int i2s_shared_reuse(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	unsigned long flags;
	int ret;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	ret = i2s_tdm->shared_params.pending == ss ? i2s_tdm->shared_params.reuse : -EINVAL;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static void i2s_shared_abort(struct snd_pcm_substream *ss, struct snd_soc_dai *dai,
			     u64 cookie, int first_error, bool shared_io_possible)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	struct snd_soc_dai_params_state *p = &i2s_tdm->shared_params;
	unsigned long flags;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (snd_soc_dai_params_abort_locked(p, dai, ss, cookie)) {
		i2s_tdm->mclk_tx_freq = p->old_clock[0];
		i2s_tdm->mclk_rx_freq = p->old_clock[1];
		i2s_tdm->shared_prepared &= ~BIT(ss->stream);
		if (shared_io_possible)
			i2s_checked_error_locked(i2s_tdm, first_error < 0 ? first_error : -EIO);
		i2s_tdm->configuring = false;
	}
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
}

static int i2s_shared_commit(struct snd_pcm_substream *ss,
			      struct snd_soc_dai *dai, u64 cookie)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	struct snd_soc_dai_params_state *p = &i2s_tdm->shared_params;
	unsigned long flags;
	int ret;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (!cookie || p->cookie != cookie || p->pending != ss ||
	    p->transaction != ss || !p->undo)
		ret = -EINVAL;
	else if (i2s_tdm->runtime_error)
		ret = i2s_tdm->runtime_error;
	else if (i2s_tdm->shutting_down)
		ret = -ESHUTDOWN;
	else if (i2s_tdm->power_transition || i2s_tdm->started || !i2s_tdm->configuring)
		ret = -EBUSY;
	else
		ret = snd_soc_dai_params_commit_locked(p, dai, ss, cookie);
	if (!ret) {
		i2s_tdm->mclk_tx_freq = 12288000;
		i2s_tdm->mclk_rx_freq = 12288000;
		i2s_tdm->shared_prepared &= ~BIT(ss->stream);
		i2s_tdm->configuring = false;
	}
	/* Any matched failure keeps the whole-chain gate until terminal CPU abort.
	 * A duplicate/stale commit has no pending identity and changes no state.
	 */
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static void i2s_shared_fault(struct snd_soc_dai *dai, int first_errno)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	unsigned long flags;

	spin_lock_irqsave(&i2s_tdm->lock, flags);
	i2s_checked_error_locked(i2s_tdm, first_errno < 0 ? first_errno : -EIO);
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
}

static int i2s_shared_free_check(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	struct snd_soc_dai_params_state *p = &i2s_tdm->shared_params;
	unsigned long flags;
	int ret = 0;

	if (ss->stream != 0 && ss->stream != 1)
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (i2s_tdm->configuring || p->pending || (i2s_tdm->started & BIT(ss->stream)))
		ret = -EBUSY;
	else if ((p->owner[ss->stream] && p->owner[ss->stream] != ss) ||
		 i2s_tdm->substreams[ss->stream] != ss)
		ret = -EINVAL;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static int i2s_shared_free(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	unsigned long flags;
	int ret;

	if (ss->stream != 0 && ss->stream != 1)
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (i2s_tdm->configuring || (i2s_tdm->started & BIT(ss->stream)))
		ret = -EBUSY;
	else
		ret = snd_soc_dai_params_free_locked(&i2s_tdm->shared_params, dai, ss);
	if (!ret)
		i2s_tdm->shared_prepared &= ~BIT(ss->stream);
	/* Faults, physical clocks and open leases are never reset by params free. */
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static int i2s_shared_sysclk(struct snd_soc_dai *dai, int clk_id,
			      unsigned int freq, int dir)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	struct snd_soc_dai_params_state *p = &i2s_tdm->shared_params;
	unsigned long flags;
	int ret;

	if (clk_id != 0 || (dir != SND_SOC_CLOCK_IN && dir != SND_SOC_CLOCK_OUT) ||
	    (!freq && dir != SND_SOC_CLOCK_OUT))
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (i2s_tdm->runtime_error)
		ret = i2s_tdm->runtime_error;
	else if (i2s_tdm->shutting_down)
		ret = -ESHUTDOWN;
	else if (p->pending || p->owner[0] || p->owner[1])
		/* This validates a value; it does not authenticate the caller/owner. */
		ret = freq == 12288000 ? 0 : -EINVAL;
	else
		ret = freq ? (freq == 12288000 ? 0 : -EINVAL) : i2s_checked_gate_locked(i2s_tdm);
	if (!ret && !freq && (!i2s_tdm->stop_proven || !i2s_tdm->irq_drained ||
			      i2s_tdm->substreams[0] || i2s_tdm->substreams[1]))
		ret = -EBUSY;
	if (!ret && !freq) {
		i2s_tdm->mclk_tx_freq = 0;
		i2s_tdm->mclk_rx_freq = 0;
	}
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static int i2s_shared_hw_params(struct snd_pcm_substream *ss,
		struct snd_pcm_hw_params *params, struct snd_soc_dai *dai)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	struct snd_soc_dai_params_state *p = &i2s_tdm->shared_params;
	struct snd_dmaengine_dai_dma_data *dma_data;
	unsigned long flags;
	unsigned int fmt;
	bool reuse, dirty;
	int ret;

	if ((ss->stream != 0 && ss->stream != 1) || params_rate(params) != 48000 ||
	    params_channels(params) != 2 || params_format(params) != SNDRV_PCM_FORMAT_S16_LE)
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	ret = i2s_tdm->runtime_error;
	if (!ret && (p->pending != ss || !p->undo || p->applied ||
		     !i2s_tdm->configuring || i2s_tdm->power_transition ||
		     i2s_tdm->shutting_down || i2s_tdm->started))
		ret = -EBUSY;
	if (!ret)
		p->applied = true;
	reuse = p->reuse;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	if (ret)
		return ret;
	if (!reuse) {
		/* The pending fixed clock is consumed by this explicit substream. */
		ret = clk_set_rate(i2s_tdm->mclk_tx, 12288000);
		if (!ret)
			ret = clk_set_rate(i2s_tdm->mclk_rx, 12288000);
		if (!ret)
			ret = rockchip_i2s_tdm_mclk_reparent(i2s_tdm);
		if (!ret && (clk_get_rate(i2s_tdm->mclk_tx) != 12288000 ||
			     clk_get_rate(i2s_tdm->mclk_rx) != 12288000))
			ret = -EINVAL;
		if (ret)
			return ret;
		ret = rockchip_i2s_tdm_params_channels(ss, params, dai);
		if (ret < 0)
			return ret;
		fmt = I2S_TXCR_VDW(16) | ret;
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		ret = i2s_tdm->runtime_error;
		if (!ret && (i2s_tdm->shutting_down || i2s_tdm->power_transition))
			ret = -ESHUTDOWN;
		if (!ret)
			ret = i2s_checked_params_dirty(ss, i2s_tdm, 4, 64, fmt, &dirty);
		if (!ret && dirty)
			ret = i2s_checked_params_trcm(ss, i2s_tdm, 4, 64, fmt);
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		if (ret)
			return ret;
	}
	/* Reuse touches only the new direction's RAM DMA configuration. */
	dma_data = snd_soc_dai_get_dma_data(dai, ss);
	dma_data->maxburst = MAXBURST_PER_FIFO;
	return 0;
}

static int i2s_shared_set_fmt(struct snd_soc_dai *dai, unsigned int fmt)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	unsigned long flags;
	int ret;

	if (fmt != (SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S))
		return -EINVAL;
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (i2s_tdm->shared_params.pending || i2s_tdm->shared_params.owner[0] ||
	    i2s_tdm->shared_params.owner[1]) {
		ret = i2s_tdm->shared_dai_fmt == fmt ? 0 : -EBUSY;
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		return ret;
	}
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	ret = i2s_checked_set_fmt(i2s_tdm, dai->dev, fmt);
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	if (!ret)
		i2s_tdm->shared_dai_fmt = fmt;
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}

static int i2s_shared_tdm_slot(struct snd_soc_dai *dai, unsigned int tx_mask,
		unsigned int rx_mask, int slots, int slot_width)
{
	/* No TDM conversion belongs to the finite ordinary-I2S profile. */
	return -EINVAL;
}
