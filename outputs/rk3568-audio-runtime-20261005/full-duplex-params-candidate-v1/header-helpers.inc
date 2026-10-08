/* NULL hooks preserve legacy behavior; partial hooks never imply legacy. */
static inline bool snd_soc_dai_hw_params_any(struct snd_soc_dai *dai)
{
	const struct snd_soc_dai_ops *ops = dai->driver->ops;

	return ops && (ops->hw_params_begin || ops->hw_params_commit ||
		       ops->hw_params_abort || ops->hw_params_reuse ||
		       ops->hw_params_free_check || ops->hw_params_fault);
}

static inline bool snd_soc_dai_hw_params_managed(struct snd_soc_dai *dai)
{
	const struct snd_soc_dai_ops *ops = dai->driver->ops;

	return ops && ops->hw_params_begin && ops->hw_params_commit &&
		ops->hw_params_abort && ops->hw_params_reuse &&
		ops->hw_params_free_check && ops->hw_params_fault && ops->hw_free;
}

static inline int snd_soc_dai_hw_params_reuse(struct snd_soc_dai *dai,
					    struct snd_pcm_substream *substream)
{
	if (!snd_soc_dai_hw_params_managed(dai))
		return -EINVAL;
	return dai->driver->ops->hw_params_reuse(substream, dai);
}

static inline int snd_soc_dai_hw_params_release(struct snd_soc_dai *dai,
					      struct snd_pcm_substream *substream)
{
	if (!snd_soc_dai_hw_params_managed(dai))
		return -EINVAL;
	return dai->driver->ops->hw_free(substream, dai);
}

static inline int snd_soc_dai_params_begin_locked(struct snd_soc_dai_params_state *p,
		struct snd_soc_dai *dai, struct snd_pcm_substream *ss, u64 *cookie)
{
	int stream = ss->stream;

	if ((stream != 0 && stream != 1) || !cookie)
		return -EINVAL;
	if (p->pending || (p->owner[stream] && p->owner[stream] != ss))
		return -EBUSY;
	if (p->generation == ~(u64)0)
		return -EOVERFLOW;
	if ((p->owner[0] || p->owner[1]) &&
	    (dai->rate != 48000 || dai->channels != 2 || dai->sample_bits != 16))
		return -EINVAL;
	p->generation++;
	p->cookie = p->generation;
	p->transaction = ss;
	p->pending = ss;
	p->old_owner = p->owner[stream];
	p->old_rate = dai->rate;
	p->old_channels = dai->channels;
	p->old_sample_bits = dai->sample_bits;
	p->reuse = p->owner[0] || p->owner[1];
	p->applied = false;
	p->undo = true;
	*cookie = p->cookie;
	return 0;
}

static inline int snd_soc_dai_params_commit_locked(struct snd_soc_dai_params_state *p,
		struct snd_soc_dai *dai, struct snd_pcm_substream *ss, u64 cookie)
{
	if (!cookie || p->cookie != cookie || p->pending != ss ||
	    p->transaction != ss || !p->undo || !p->applied)
		return -EINVAL;
	p->owner[ss->stream] = ss;
	dai->rate = 48000;
	dai->channels = 2;
	dai->sample_bits = 16;
	p->pending = NULL;
	/* Keep undo valid until the next serialized begin/release. */
	return 0;
}

static inline bool snd_soc_dai_params_abort_locked(struct snd_soc_dai_params_state *p,
		struct snd_soc_dai *dai, struct snd_pcm_substream *ss, u64 cookie)
{
	if (!cookie || p->cookie != cookie || p->transaction != ss || !p->undo)
		return false;
	p->owner[ss->stream] = p->old_owner;
	dai->rate = p->old_rate;
	dai->channels = p->old_channels;
	dai->sample_bits = p->old_sample_bits;
	p->pending = NULL;
	p->transaction = NULL;
	p->undo = false;
	p->applied = false;
	return true;
}

static inline int snd_soc_dai_params_free_locked(struct snd_soc_dai_params_state *p,
		struct snd_soc_dai *dai, struct snd_pcm_substream *ss)
{
	if (ss->stream != 0 && ss->stream != 1)
		return -EINVAL;
	if (p->pending)
		return -EBUSY;
	if (p->owner[ss->stream] && p->owner[ss->stream] != ss)
		return -EINVAL;
	p->owner[ss->stream] = NULL;
	p->transaction = NULL;
	p->undo = false;
	if (!p->owner[0] && !p->owner[1]) {
		dai->rate = 0;
		dai->channels = 0;
		dai->sample_bits = 0;
	}
	return 0;
}
