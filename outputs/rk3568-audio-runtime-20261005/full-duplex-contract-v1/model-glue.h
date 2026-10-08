/* SPDX-License-Identifier: MIT */
struct snd_soc_component;
struct snd_soc_component_driver {
    int (*trigger)(struct snd_soc_component *, struct snd_pcm_substream *, int);
};
struct snd_soc_component {
    struct device *dev;
    const char *name;
    const struct snd_soc_component_driver *driver;
    unsigned int active;
    void *mark_pm;
};
struct snd_soc_dai_ops {
    int (*set_sysclk)(struct snd_soc_dai *, int, unsigned int, int);
    int (*startup)(struct snd_pcm_substream *, struct snd_soc_dai *);
    void (*shutdown)(struct snd_pcm_substream *, struct snd_soc_dai *);
    int (*trigger)(struct snd_pcm_substream *, int, struct snd_soc_dai *);
};
struct snd_soc_dai_driver { const struct snd_soc_dai_ops *ops; bool symmetric_rates, symmetric_channels, symmetric_samplebits; };
struct snd_soc_ops {
    int (*startup)(struct snd_pcm_substream *);
    void (*shutdown)(struct snd_pcm_substream *);
    int (*trigger)(struct snd_pcm_substream *, int);
};
struct snd_soc_dai_link { const struct snd_soc_ops *ops; const char *name; bool dynamic, no_pcm, symmetric_rates, symmetric_channels, symmetric_samplebits; };
struct snd_soc_card { void *data; pthread_mutex_t pcm_mutex; int pcm_subclass; };
struct snd_pcm_runtime { struct { unsigned int info, rates, channels_min, channels_max, rate_min, rate_max; uint64_t formats; } hw; };
struct simple_dai_props { struct asoc_simple_dai *cpu_dai, *codec_dai; unsigned int mclk_fs; };
struct asoc_simple_priv { struct simple_dai_props *dai_props; };
struct rk817_codec_priv { unsigned int stereo_sysclk; };
struct snd_soc_pcm_runtime {
    struct device *dev;
    struct snd_soc_card *card;
    struct snd_soc_dai_link *dai_link;
    struct snd_soc_component **components;
    struct snd_soc_dai **dais;
    int num_components, num_cpus, num_codecs;
    unsigned int num;
    struct snd_pcm_substream *mark_startup;
};
#include "actual-iteration-mark-macros.h"
#define mutex_lock_nested(lock, subclass) ((void)(subclass), pthread_mutex_lock(lock))
static void model_mutex_unlock(pthread_mutex_t *lock);
#define mutex_unlock(lock) model_mutex_unlock(lock)
#define lockdep_assert_held(lock) ((void)(lock))
#define simple_priv_to_props(priv, index) ((priv)->dai_props + (index))
#define soc_component_ret(c, r) _soc_component_ret(c, __func__, r)
#define soc_dai_ret(d, r) _soc_dai_ret(d, __func__, r)
#define soc_link_ret(rtd, r) _soc_link_ret(rtd, __func__, r)
static void *snd_soc_component_get_drvdata(struct snd_soc_component *component) { return dev_get_drvdata(component->dev); }
static struct snd_soc_pcm_runtime *asoc_substream_to_rtd(struct snd_pcm_substream *ss) { return ss->private_data; }
static struct snd_soc_dai *asoc_rtd_to_cpu(struct snd_soc_pcm_runtime *rtd, unsigned int i) { return rtd->dais[i]; }
static struct snd_soc_dai *asoc_rtd_to_codec(struct snd_soc_pcm_runtime *rtd, unsigned int i) { return rtd->dais[rtd->num_cpus + i]; }
static void *snd_soc_card_get_drvdata(struct snd_soc_card *card) { return card->data; }
static int snd_soc_component_set_sysclk(struct snd_soc_component *c, int id, int src, unsigned int f, int d)
{ (void)c; (void)id; (void)src; (void)f; (void)d; return -ENOTSUPP; }
static void pinctrl_pm_select_default_state(struct device *dev) { (void)dev; }
static void pinctrl_pm_select_sleep_state(struct device *dev) { (void)dev; }
static bool snd_soc_component_active(struct snd_soc_component *component) { return component->active != 0; }
static bool soc_pcm_has_symmetry(struct snd_pcm_substream *ss) { (void)ss; return true; }
static int snd_pcm_hw_constraint_single(struct snd_pcm_runtime *runtime, int parameter, unsigned int value)
{ (void)runtime; (void)parameter; (void)value; return model_constraint_error; }
static void soc_pcm_apply_msb(struct snd_pcm_substream *ss) { (void)ss; }
static void soc_pcm_init_runtime_hw(struct snd_pcm_substream *ss)
{
    ss->runtime->hw.rates = 1;
    ss->runtime->hw.formats = 1;
    ss->runtime->hw.channels_min = ss->runtime->hw.channels_max = 2;
    ss->runtime->hw.rate_min = ss->runtime->hw.rate_max = 48000;
}
static int soc_pcm_components_open(struct snd_pcm_substream *ss) { ss->component_opened = true; return 0; }
static void soc_pcm_components_close(struct snd_pcm_substream *ss, int rollback) { (void)rollback; ss->component_opened = false; }
static void snd_soc_dapm_stream_stop(struct snd_soc_pcm_runtime *rtd, int stream) { (void)rtd; (void)stream; }
