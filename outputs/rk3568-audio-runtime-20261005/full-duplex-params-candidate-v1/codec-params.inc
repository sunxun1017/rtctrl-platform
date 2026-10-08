static int rk817_shared_startup(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	int ret;

	if (!rk817->shared_params_enabled || dai->id != RK817_HIFI ||
	    (ss->stream != 0 && ss->stream != 1))
		return -EINVAL;
	mutex_lock(&rk817->params_lock);
	ret = rk817->params_error;
	if (!ret && (rk817->shared_params.pending || rk817->shared_open[ss->stream]))
		ret = -EBUSY;
	if (!ret)
		rk817->shared_open[ss->stream] = ss;
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static int rk817_shared_begin(struct snd_pcm_substream *ss,
		struct snd_pcm_hw_params *params, struct snd_soc_dai *dai, u64 *cookie)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	struct snd_soc_dai_params_state *p = &rk817->shared_params;
	int ret;

	if (!rk817->shared_params_enabled || dai->id != RK817_HIFI ||
	    (ss->stream != 0 && ss->stream != 1) || params_rate(params) != 48000 ||
	    params_channels(params) != 2 || params_format(params) != SNDRV_PCM_FORMAT_S16_LE ||
	    rk817->pdmdata_out_enable || rk817->adc_for_loopback)
		return -EINVAL;
	mutex_lock(&rk817->params_lock);
	ret = rk817->params_error;
	if (!ret && (rk817->shared_open[ss->stream] != ss ||
	    rk817->shared_dai_fmt != (SND_SOC_DAIFMT_CBS_CFS |
		SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S)))
		ret = -EINVAL;
	if (!ret)
		ret = snd_soc_dai_params_begin_locked(p, dai, ss, cookie);
	if (!ret)
		p->old_clock[0] = rk817->stereo_sysclk;
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static int rk817_shared_reuse(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	int ret;

	mutex_lock(&rk817->params_lock);
	ret = rk817->shared_params.pending == ss ? rk817->shared_params.reuse : -EINVAL;
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static void rk817_shared_abort(struct snd_pcm_substream *ss, struct snd_soc_dai *dai,
			       u64 cookie, int first_error, bool shared_io_possible)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	struct snd_soc_dai_params_state *p = &rk817->shared_params;

	mutex_lock(&rk817->params_lock);
	if (snd_soc_dai_params_abort_locked(p, dai, ss, cookie)) {
		rk817->stereo_sysclk = p->old_clock[0];
		if (shared_io_possible && !rk817->params_error)
			rk817->params_error = first_error < 0 ? first_error : -EIO;
	}
	mutex_unlock(&rk817->params_lock);
}

static int rk817_shared_commit(struct snd_pcm_substream *ss,
				struct snd_soc_dai *dai, u64 cookie)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	struct snd_soc_dai_params_state *p = &rk817->shared_params;
	int ret;

	mutex_lock(&rk817->params_lock);
	if (!cookie || p->cookie != cookie || p->pending != ss ||
	    p->transaction != ss || !p->undo) {
		mutex_unlock(&rk817->params_lock);
		return -EINVAL; /* Duplicate/stale commit cannot undo a committed owner. */
	}
	ret = rk817->params_error;
	if (!ret)
		ret = snd_soc_dai_params_commit_locked(p, dai, ss, cookie);
	if (!ret)
		rk817->stereo_sysclk = 12288000;
	else if (snd_soc_dai_params_abort_locked(p, dai, ss, cookie))
		rk817->stereo_sysclk = p->old_clock[0];
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static void rk817_shared_fault(struct snd_soc_dai *dai, int first_errno)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);

	mutex_lock(&rk817->params_lock);
	if (!rk817->params_error)
		rk817->params_error = first_errno < 0 ? first_errno : -EIO;
	mutex_unlock(&rk817->params_lock);
}

static int rk817_shared_free_check(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	struct snd_soc_dai_params_state *p = &rk817->shared_params;
	int ret = 0;

	if (dai->id != RK817_HIFI || (ss->stream != 0 && ss->stream != 1))
		return -EINVAL;
	mutex_lock(&rk817->params_lock);
	if (p->pending)
		ret = -EBUSY;
	else if ((p->owner[ss->stream] && p->owner[ss->stream] != ss) ||
		 rk817->shared_open[ss->stream] != ss)
		ret = -EINVAL;
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static int rk817_shared_free(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	int ret;

	if (dai->id != RK817_HIFI)
		return -EINVAL;
	mutex_lock(&rk817->params_lock);
	ret = snd_soc_dai_params_free_locked(&rk817->shared_params, dai, ss);
	/* Keep sticky params_error and the separately owned MCLK lease/request. */
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static int rk817_shared_sysclk(struct snd_soc_dai *dai, int clk_id,
				unsigned int freq, int dir)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	struct snd_soc_dai_params_state *p = &rk817->shared_params;
	int ret = 0;

	if (dai->id != RK817_HIFI || clk_id != 0 ||
	    (dir != SND_SOC_CLOCK_IN && dir != SND_SOC_CLOCK_OUT) ||
	    (!freq && dir != SND_SOC_CLOCK_IN))
		return -EINVAL;
	mutex_lock(&rk817->params_lock);
	if (rk817->params_error)
		ret = rk817->params_error;
	else if (p->pending || p->owner[0] || p->owner[1])
		/* Value validation only; this setter has no owner identity parameter. */
		ret = freq == 12288000 ? 0 : -EINVAL;
	else if (freq)
		ret = freq == 12288000 ? 0 : -EINVAL;
	else if (snd_soc_dai_active(dai))
		ret = -EINVAL;
	else
		rk817->stereo_sysclk = 0;
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static int rk817_shared_hw_params(struct snd_pcm_substream *ss,
		struct snd_pcm_hw_params *params, struct snd_soc_dai *dai)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	struct snd_soc_dai_params_state *p = &rk817->shared_params;
	int ret;

	if (dai->id != RK817_HIFI || (ss->stream != 0 && ss->stream != 1) ||
	    params_rate(params) != 48000 || params_channels(params) != 2 ||
	    params_format(params) != SNDRV_PCM_FORMAT_S16_LE)
		return -EINVAL;
	mutex_lock(&rk817->params_lock);
	ret = rk817->params_error;
	if (!ret && (p->pending != ss || !p->undo || p->applied))
		ret = -EBUSY;
	if (!ret) {
		p->applied = true;
		/* Whole real RK817 PLL/width/rate function only for first configuration. */
		if (!p->reuse)
			ret = rk817_hw_params(ss, params, dai);
	}
	if (ret < 0 && p->pending == ss && p->applied && !p->reuse && !rk817->params_error)
		rk817->params_error = ret;
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static int rk817_shared_set_fmt(struct snd_soc_dai *dai, unsigned int fmt)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	struct snd_soc_dai_params_state *p = &rk817->shared_params;
	int ret;

	if (dai->id != RK817_HIFI ||
	    fmt != (SND_SOC_DAIFMT_CBS_CFS | SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_I2S))
		return -EINVAL;
	mutex_lock(&rk817->params_lock);
	ret = rk817->params_error;
	if (!ret && (p->pending || p->owner[0] || p->owner[1]))
		ret = rk817->shared_dai_fmt == fmt ? 0 : -EBUSY;
	else if (!ret) {
		ret = rk817_set_dai_fmt(dai, fmt);
		if (!ret)
			rk817->shared_dai_fmt = fmt;
		else if (!rk817->params_error)
			rk817->params_error = ret;
	}
	mutex_unlock(&rk817->params_lock);
	return ret;
}

static void rk817_shared_shutdown(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
	struct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
	bool peer;
	int ret;

	/* Startup failure on checked voice must never pulse the hifi clock. */
	if (dai->id != RK817_HIFI)
		return;
	mutex_lock(&rk817->params_lock);
	if ((ss->stream != 0 && ss->stream != 1) || rk817->shared_open[ss->stream] != ss) {
		mutex_unlock(&rk817->params_lock);
		return; /* Failed startup/idempotent close owns no open lease. */
	}
	mutex_unlock(&rk817->params_lock);
	ret = rk817_shared_free(ss, dai);
	if (ret) {
		rk817_shared_fault(dai, ret);
		return;
	}
	mutex_lock(&rk817->params_lock);
	rk817->shared_open[ss->stream] = NULL;
	peer = rk817->shared_open[0] || rk817->shared_open[1] ||
		rk817->shared_params.owner[0] || rk817->shared_params.owner[1];
	if (!peer)
		rk817_codec_shutdown(ss, dai);
	mutex_unlock(&rk817->params_lock);
}
