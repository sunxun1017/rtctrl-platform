static int soc_pcm_hw_free_transaction(struct snd_pcm_substream *ss)
{
	struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(ss);
	struct snd_soc_dai *cpu = asoc_rtd_to_cpu(rtd, 0);
	struct snd_soc_dai *codec = asoc_rtd_to_codec(rtd, 0);
	struct snd_soc_dai *dai;
	int i, ret, next;

	/* Both pure checks precede any owner/cache mutation, mute or DMA teardown. */
	ret = cpu->driver->ops->hw_params_free_check(ss, cpu);
	if (ret < 0)
		return ret;
	ret = codec->driver->ops->hw_params_free_check(ss, codec);
	if (ret < 0)
		return ret;
	/* CPU rechecks concurrent START under its state lock. */
	ret = snd_soc_dai_hw_params_release(cpu, ss);
	if (ret < 0)
		return ret;
	ret = snd_soc_dai_hw_params_release(codec, ss);
	if (ret < 0) {
		soc_pcm_params_fault(rtd, ret);
		return ret; /* Half-release is FAULT, never an atomic restore claim. */
	}
	for_each_rtd_dais(rtd, i, dai) {
		if (snd_soc_dai_stream_active(dai, ss->stream) == 1 &&
		    soc_pcm_has_mute(dai, ss->stream)) {
			next = snd_soc_dai_digital_mute(dai, 1, ss->stream);
			if (next < 0 && !ret)
				ret = next;
		}
	}
	next = soc_pcm_params_link_free(ss);
	if (next < 0 && !ret)
		ret = next;
	next = soc_pcm_params_component_free(ss, NULL);
	if (next < 0 && !ret)
		ret = next;
	if (ret < 0)
		soc_pcm_params_fault(rtd, ret);
	return ret;
}
