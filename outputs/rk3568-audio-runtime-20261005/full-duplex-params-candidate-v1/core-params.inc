/* 0: legacy; 1: complete single-link transaction; negative: reject before I/O. */
static int soc_pcm_params_managed(struct snd_soc_pcm_runtime *rtd)
{
	struct snd_soc_dai *dai;
	int i;
	bool any = false;

	for_each_rtd_dais(rtd, i, dai)
		any |= snd_soc_dai_hw_params_any(dai);
	if (!any)
		return 0;
	if (rtd->num_cpus != 1 || rtd->num_codecs != 1 ||
	    rtd->card->num_links != 1 || rtd->card->num_rtd != 1 ||
	    rtd->dai_link->dynamic || rtd->dai_link->no_pcm)
		return -EINVAL;
	for_each_rtd_dais(rtd, i, dai)
		if (!snd_soc_dai_hw_params_managed(dai))
			return -EINVAL;
	return 1;
}

static void soc_pcm_params_fault(struct snd_soc_pcm_runtime *rtd, int first_errno)
{
	asoc_rtd_to_cpu(rtd, 0)->driver->ops->hw_params_fault(asoc_rtd_to_cpu(rtd, 0), first_errno);
	asoc_rtd_to_codec(rtd, 0)->driver->ops->hw_params_fault(asoc_rtd_to_codec(rtd, 0), first_errno);
}

/* Checked counterpart of the legacy void component dispatcher, same prefix order. */
static int soc_pcm_params_component_free(struct snd_pcm_substream *ss,
					 struct snd_soc_component *last)
{
	struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(ss);
	struct snd_soc_component *component;
	int i, ret, first = 0;

	for_each_rtd_components(rtd, i, component) {
		if (component == last)
			break;
		if (component->driver->hw_free) {
			ret = component->driver->hw_free(component, ss);
			if (ret < 0) {
				dev_err(component->dev, "checked component hw_free failed: %d\n", ret);
				if (!first)
					first = ret;
			}
		}
	}
	return first;
}

/* Checked counterpart of the legacy void machine dispatcher. */
static int soc_pcm_params_link_free(struct snd_pcm_substream *ss)
{
	struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(ss);

	if (rtd->dai_link->ops && rtd->dai_link->ops->hw_free)
		return rtd->dai_link->ops->hw_free(ss);
	return 0;
}

static int soc_pcm_hw_params_transaction(struct snd_pcm_substream *ss,
					 struct snd_pcm_hw_params *params)
{
	struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(ss);
	struct snd_soc_dai *cpu = asoc_rtd_to_cpu(rtd, 0);
	struct snd_soc_dai *codec = asoc_rtd_to_codec(rtd, 0);
	struct snd_soc_component *component = NULL;
	u64 cpu_cookie = 0, codec_cookie = 0;
	bool shared_io_possible = false, machine_attempted = false;
	bool component_attempted = false;
	int ret, next, cpu_reuse, codec_reuse;

	/* This finite contract does not support codec slot fixups or conversion. */
	if (codec->tx_mask || codec->rx_mask ||
	    !snd_soc_dai_stream_valid(cpu, ss->stream) ||
	    !snd_soc_dai_stream_valid(codec, ss->stream))
		return -EINVAL;
	ret = cpu->driver->ops->hw_params_begin(ss, params, cpu, &cpu_cookie);
	if (ret < 0)
		return ret;
	ret = codec->driver->ops->hw_params_begin(ss, params, codec, &codec_cookie);
	if (ret < 0)
		goto abort;
	cpu_reuse = snd_soc_dai_hw_params_reuse(cpu, ss);
	codec_reuse = snd_soc_dai_hw_params_reuse(codec, ss);
	if (cpu_reuse < 0 || codec_reuse < 0 || cpu_reuse != codec_reuse) {
		ret = cpu_reuse < 0 ? cpu_reuse : codec_reuse < 0 ? codec_reuse : -EINVAL;
		goto abort;
	}
	shared_io_possible = !cpu_reuse;
	machine_attempted = true;
	ret = snd_soc_link_hw_params(ss, params);
	if (ret < 0)
		goto abort;
	ret = snd_soc_dai_hw_params(codec, ss, params);
	if (ret < 0)
		goto abort;
	ret = snd_soc_dai_hw_params(cpu, ss, params);
	if (ret < 0)
		goto abort;
	component_attempted = true;
	ret = snd_soc_pcm_component_hw_params(ss, params, &component);
	if (ret < 0)
		goto abort;
	ret = codec->driver->ops->hw_params_commit(ss, codec, codec_cookie);
	if (ret < 0)
		goto abort;
	ret = cpu->driver->ops->hw_params_commit(ss, cpu, cpu_cookie);
	if (ret < 0)
		goto abort;
	snd_soc_dapm_update_dai(ss, params, codec);
	snd_soc_dapm_update_dai(ss, params, cpu);
	return 0;
abort:
	/* First errno survives all teardown; no legacy rate=0 or double DAI free. */
	if (component_attempted)
		if (soc_pcm_params_component_free(ss, component) < 0)
			soc_pcm_params_fault(rtd, ret);
	if (machine_attempted) {
		next = soc_pcm_params_link_free(ss);
		if (next < 0)
			soc_pcm_params_fault(rtd, ret);
	}
	if (codec_cookie)
		codec->driver->ops->hw_params_abort(ss, codec, codec_cookie,
						 ret, shared_io_possible);
	if (cpu_cookie)
		cpu->driver->ops->hw_params_abort(ss, cpu, cpu_cookie,
						 ret, shared_io_possible);
	return ret;
}
