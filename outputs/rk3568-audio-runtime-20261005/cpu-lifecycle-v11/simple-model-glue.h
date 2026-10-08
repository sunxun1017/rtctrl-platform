/* SPDX-License-Identifier: MIT */
/* Explicit ASoC/CCF boundaries, not kernel runtime ABI or hardware. */
#define ENOTSUPP 524
#define DBG(...) ((void)0)
struct snd_soc_component { struct device *dev; };
struct rk817_codec_priv { unsigned int stereo_sysclk; };
struct snd_soc_dai_ops {
    int (*set_sysclk)(struct snd_soc_dai *, int, unsigned int, int);
};
struct snd_soc_dai_driver { const struct snd_soc_dai_ops *ops; };
struct snd_soc_card { void *data; };
struct simple_dai_props {
    struct asoc_simple_dai *cpu_dai;
    struct asoc_simple_dai *codec_dai;
    unsigned int mclk_fs;
};
struct asoc_simple_priv { struct simple_dai_props *dai_props; };
struct snd_soc_pcm_runtime {
    struct snd_soc_card *card;
    unsigned int num;
    struct snd_soc_dai *cpu;
    struct snd_soc_dai *codec;
};
static struct snd_soc_pcm_runtime model_rtd;
static unsigned int model_diagnostics, model_unexpected, model_clock_releases;
static int model_cpu_sysclk_return;
static void *snd_soc_component_get_drvdata(struct snd_soc_component *component)
{
    return dev_get_drvdata(component->dev);
}
static struct snd_soc_pcm_runtime *asoc_substream_to_rtd(struct snd_pcm_substream *substream)
{
    (void)substream;
    return &model_rtd;
}
static struct snd_soc_dai *asoc_rtd_to_cpu(struct snd_soc_pcm_runtime *rtd, unsigned int index)
{
    if (index) model_unexpected++;
    return rtd->cpu;
}
static struct snd_soc_dai *asoc_rtd_to_codec(struct snd_soc_pcm_runtime *rtd, unsigned int index)
{
    if (index) model_unexpected++;
    return rtd->codec;
}
static void *snd_soc_card_get_drvdata(struct snd_soc_card *card)
{
    return card->data;
}
#define simple_priv_to_props(priv, index) ((priv)->dai_props + (index))
static int soc_dai_ret(struct snd_soc_dai *dai, int ret)
{
    if (dai == model_rtd.cpu) model_cpu_sysclk_return = ret;
    if (ret < 0 && ret != -ENOTSUPP) model_diagnostics++;
    return ret;
}
static int snd_soc_component_set_sysclk(struct snd_soc_component *component,
                                       int clk_id, int source, unsigned int freq, int dir)
{
    (void)component;
    (void)clk_id;
    (void)source;
    (void)freq;
    (void)dir;
    model_unexpected++;
    return -EOPNOTSUPP;
}
static void clk_disable_unprepare(struct clk *clk)
{
    /* Real CCF treats NULL as a no-op; the sample simple children have no clk. */
    if (clk) model_clock_releases++;
}
