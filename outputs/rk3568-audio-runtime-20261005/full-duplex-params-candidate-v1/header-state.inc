/* Fixed two-slot software ownership; callers hold their endpoint state lock. */
struct snd_soc_dai_params_state {
	struct snd_pcm_substream *owner[2];
	struct snd_pcm_substream *pending;
	struct snd_pcm_substream *transaction;
	struct snd_pcm_substream *old_owner;
	u64 generation, cookie;
	unsigned int old_rate, old_channels, old_sample_bits;
	unsigned int old_clock[2];
	bool reuse, applied, undo;
};
