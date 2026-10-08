/* SPDX-License-Identifier: MIT */
/* Explicit kernel API boundaries. They do not execute I2C/CCF/PL330/DAPM. */
#include "rk817_codec.h"
static int snd_soc_component_write(struct snd_soc_component *component, unsigned int reg, unsigned int value)
{
    (void)component;
    if (reg >= 2048) return -EINVAL;
    codec_io_calls++;
    codec_registers[reg] = value;
    params_note("CODEC_WRITE", reg, 0);
    return 0;
}
static int snd_soc_component_update_bits(struct snd_soc_component *component, unsigned int reg, unsigned int mask, unsigned int value)
{
    (void)component;
    if (reg >= 2048) return -EINVAL;
    codec_io_calls++;
    codec_registers[reg] = (codec_registers[reg] & ~mask) | (value & mask);
    if (reg == RK817_CODEC_APLL_CFG5 && (mask & PLL_PW_DOWN)) codec_pll_calls++;
    params_note("CODEC_UPDATE", reg, 0);
    return 0;
}
static void usleep_range(unsigned int low, unsigned int high) { (void)low; (void)high; }
#define pr_err(...) model_log(__VA_ARGS__)
static unsigned int hweight_long(unsigned long value) { return __builtin_popcountl(value); }
static struct snd_interval *hw_param_interval(struct snd_pcm_hw_params *p, snd_pcm_hw_param_t var)
{ return &p->intervals[var - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL]; }
/* Format conversion API for this finite input set; not pcm_misc production body. */
static int snd_pcm_format_physical_width(snd_pcm_format_t format)
{
    if (format == SNDRV_PCM_FORMAT_S16_LE) return 16;
    if (format == SNDRV_PCM_FORMAT_S24_LE || format == SNDRV_PCM_FORMAT_S32_LE) return 32;
    return -EINVAL;
}
static bool snd_soc_dai_stream_valid(struct snd_soc_dai *dai, int stream)
{ (void)dai; return stream == SNDRV_PCM_STREAM_PLAYBACK || stream == SNDRV_PCM_STREAM_CAPTURE; }
static void snd_soc_dapm_update_dai(struct snd_pcm_substream *ss, struct snd_pcm_hw_params *p, struct snd_soc_dai *dai)
{ (void)p; params_note(dai->component->model_id ? "DAPM_CODEC_API" : "DAPM_CPU_API", ss->stream, 0); }
/* Only the muted HW_FREE/close boundary is modeled, not RK817 GPIO/path controls. */
static int params_codec_mute_api(struct snd_soc_dai *dai, int mute, int stream)
{ (void)dai; params_note("CODEC_MUTE_API", stream, mute); return mute == 1 ? 0 : -ENOTSUPP; }
struct dma_slave_config { unsigned int rate, channels, maxburst; };
struct dma_chan { unsigned int stream; struct dma_slave_config config; };
struct snd_dmaengine_pcm_config {
    int (*prepare_slave_config)(struct snd_pcm_substream *, struct snd_pcm_hw_params *, struct dma_slave_config *);
};
struct dmaengine_pcm { const struct snd_dmaengine_pcm_config *config; };
static struct dmaengine_pcm params_dma_pcm;
static struct dma_chan params_channels_dma[2];
static struct dmaengine_pcm *soc_component_to_pcm(struct snd_soc_component *c)
{ (void)c; return &params_dma_pcm; }
static struct dma_chan *snd_dmaengine_pcm_get_chan(struct snd_pcm_substream *ss)
{ return &params_channels_dma[ss->stream]; }
static int snd_hwparams_to_dma_slave_config(struct snd_pcm_substream *ss, struct snd_pcm_hw_params *p, struct dma_slave_config *config)
{ (void)ss; config->rate = params_rate(p); config->channels = params_channels(p); return 0; }
static void snd_dmaengine_pcm_set_config_from_dai_data(struct snd_pcm_substream *ss, const struct snd_dmaengine_dai_dma_data *data, struct dma_slave_config *config)
{ (void)ss; config->maxburst = data->maxburst; }
static int dmaengine_slave_config(struct dma_chan *chan, struct dma_slave_config *config)
{
    int result = params_inject_slave_config ? -ENOSPC : 0;
    params_inject_slave_config = false;
    chan->config = *config; /* A permitted partial side effect even on API failure. */
    params_note("DMA_SLAVE_CONFIG_API", chan->stream, result);
    return result;
}
