static int i2s_checked_prepare(struct snd_pcm_substream *substream,
			       struct snd_soc_dai *dai)
{
	struct rk_i2s_tdm_dev *i2s_tdm = to_info(dai);
	unsigned long flags;
	int ret;

	if (!i2s_tdm->checked_lifecycle)
		return 0;
	if (i2s_tdm->shared_params_enabled) {
		int stream = substream->stream;
		if (stream != 0 && stream != 1)
			return -EINVAL;
		spin_lock_irqsave(&i2s_tdm->lock, flags);
		ret = i2s_tdm->runtime_error;
		if (!ret && i2s_tdm->shutting_down)
			ret = -ESHUTDOWN;
		if (!ret && !READ_ONCE(i2s_tdm->ready))
			ret = -EAGAIN;
		if (!ret && (i2s_tdm->configuring || i2s_tdm->power_transition ||
			i2s_tdm->shared_params.pending || i2s_tdm->starting ||
			(i2s_tdm->started & BIT(stream))))
			ret = -EBUSY;
		if (!ret && (i2s_tdm->substreams[stream] != substream ||
			i2s_tdm->shared_params.owner[stream] != substream))
			ret = -EINVAL;
		if (!ret) {
			if (i2s_tdm->started)
				ret = i2s_trcm_quiet_locked(i2s_tdm, stream);
			else
				ret = i2s_trcm_joint_locked(i2s_tdm, 0);
			if (ret)
				i2s_trcm_joint_locked(i2s_tdm, ret);
		}
		if (!ret)
			i2s_tdm->shared_prepared |= BIT(stream);
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);
		return ret;
	}
	spin_lock_irqsave(&i2s_tdm->lock, flags);
	ret = i2s_checked_gate_locked(i2s_tdm);
	if (!ret && !READ_ONCE(i2s_tdm->ready))
		ret = -EAGAIN;
	if (!ret)
		ret = i2s_checked_stop_locked(i2s_tdm, substream->stream, true);
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);
	return ret;
}
