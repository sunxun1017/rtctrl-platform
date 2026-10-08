/* SPDX-License-Identifier: MIT */
/* Kernel primitive boundary only; no physical I2C/CCF/GPIO/PM is executed. */
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rk817_codec.h"
#define BIT(bit) (1U << (bit))

typedef uint64_t u64;
struct mutex { pthread_mutex_t native; };
static void mutex_lock(struct mutex *lock) { pthread_mutex_lock(&lock->native); }
static void mutex_unlock(struct mutex *lock) { pthread_mutex_unlock(&lock->native); }
#define DBG(...) do { } while (0)
#define dev_err(...) do { } while (0)
#define dev_dbg(...) do { } while (0)
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define RK817_CODEC_PLAYBACK 1
#define RK817_CODEC_CAPTURE 2
#define RK817_CODEC_INCALL 4
#define RK817_CODEC_ALL 7
#define CODEC_SET_SPK 1
#define CODEC_SET_HP 2
#define RK817_HIFI 0
#define RK817_VOICE 1
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
#define SND_SOC_DAIFMT_I2S 1
#define SND_SOC_DAIFMT_CBS_CFS (4 << 12)
#define SND_SOC_DAIFMT_CBM_CFM (1 << 12)
#define SND_SOC_DAIFMT_NB_NF 0
#define SND_SOC_DAIFMT_MASTER_MASK 0xf000
#define SND_SOC_DAIFMT_INV_MASK 0x0f00
#define SND_SOC_DAIFMT_FORMAT_MASK 0x000f
#define SND_SOC_CLOCK_IN 0
#define SND_SOC_CLOCK_OUT 1

struct snd_soc_component;
struct snd_soc_card;
struct snd_soc_component_driver { const char *name; };
struct list_head { unsigned int count; };
struct snd_card {
    pthread_mutex_t files_lock;
    struct list_head files_list;
    unsigned int remove_sleep;
    bool shutdown;
};
struct snd_soc_dai_driver;
struct snd_pcm_substream { int stream; };
struct snd_soc_dai {
    int id;
    struct snd_soc_component *component;
    struct snd_soc_dai_driver *driver;
    unsigned int rate, channels, sample_bits;
};
struct snd_soc_dai_ops {
    void *hw_params_begin, *hw_params_commit, *hw_params_abort;
    void *hw_params_reuse, *hw_params_free_check, *hw_params_fault;
};
struct snd_soc_dai_driver { struct snd_soc_dai_ops *ops; };
struct regmap { int unused; };
struct rk808 { int unused; };
struct clk { int references; };
struct gpio_desc { int value; };
struct snd_soc_dapm_context { bool idle_bias_off; int bias; };
struct device { void *data; };
struct snd_soc_component {
    void *data;
    struct device *dev;
    struct regmap *regmap;
    struct snd_soc_dapm_context dapm;
    bool suspended;
    struct snd_soc_card *card;
    const struct snd_soc_component_driver *driver;
    struct list_head card_list;
};
struct snd_kcontrol { struct snd_soc_component *component; };
struct snd_ctl_elem_value { union { struct { long value[2]; } integer; } value; };

#include "actual-state.h"
#include "actual-codec-type.h"
static struct rk817_codec_priv codec;
static struct snd_soc_component component;
static struct snd_soc_dai dai;
static struct clk clock_model;
static struct snd_pcm_substream streams[2] = {{0}, {1}};
static struct snd_kcontrol control;
static unsigned int registers_model[256];
static unsigned int io_count, gpio_count, clk_enable_count, clk_disable_count;
static unsigned int fail_at, fail_at_second;
static int clk_error, io_error = -EREMOTEIO, io_error_second = -ENXIO;
static bool check_io_lock, io_without_lock, check_publish, premature_publish;
static long wanted_old_path;
static unsigned int watched_stream;
static unsigned int checked, failed;

static void expect(const char *name, bool ok)
{
    printf("CHECK %s %d\n", name, ok);
    checked++;
    failed += !ok;
}

static void primitive_boundary(void)
{
    if (check_io_lock) {
        int ret = pthread_mutex_trylock(&codec.params_lock.native);
        if (!ret) {
            io_without_lock = true;
            pthread_mutex_unlock(&codec.params_lock.native);
        } else if (ret != EBUSY) {
            abort();
        }
    }
    if (check_publish) {
        long path = watched_stream ? codec.capture_path : codec.playback_path;
        if (path != wanted_old_path)
            premature_publish = true;
    }
}

static void *snd_soc_component_get_drvdata(struct snd_soc_component *c) { return c->data; }
static struct snd_soc_component *snd_soc_kcontrol_component(struct snd_kcontrol *k) { return k->component; }
static int snd_soc_component_write(struct snd_soc_component *c, unsigned int reg, unsigned int value)
{
    (void)c;
    if (reg >= ARRAY_SIZE(registers_model)) abort();
    primitive_boundary();
    io_count++;
    /* Error may follow partial physical mutation, deliberately no fake rollback. */
    registers_model[reg] = value;
    int ret = io_count == fail_at ? io_error : (io_count == fail_at_second ? io_error_second : 0);
    printf("IO %u WRITE %u %u %d\n", io_count, reg, value, ret);
    return ret;
}
static int snd_soc_component_update_bits(struct snd_soc_component *c, unsigned int reg,
                                          unsigned int mask, unsigned int value)
{
    (void)c;
    if (reg >= ARRAY_SIZE(registers_model)) abort();
    primitive_boundary();
    io_count++;
    registers_model[reg] = (registers_model[reg] & ~mask) | (value & mask);
    int ret = io_count == fail_at ? io_error : (io_count == fail_at_second ? io_error_second : 0);
    printf("IO %u UPDATE %u %u %u %d\n", io_count, reg, mask, value, ret);
    return ret;
}
static int clk_prepare_enable(struct clk *clock)
{
    primitive_boundary();
    clk_enable_count++;
    if (!clk_error) clock->references++;
    printf("CLK ENABLE %d %d\n", clk_error, clock->references);
    return clk_error;
}
static void clk_disable_unprepare(struct clk *clock)
{
    primitive_boundary();
    clk_disable_count++;
    clock->references--;
    if (clock->references < 0) abort();
    printf("CLK DISABLE %d\n", clock->references);
}
static void gpiod_set_value(struct gpio_desc *gpio, int value)
{ primitive_boundary(); gpio_count++; gpio->value = value; }
static void msleep(unsigned int ms) { (void)ms; }
static void usleep_range(unsigned int low, unsigned int high) { (void)low; (void)high; }

/* PM iteration uses a finite array fixture; production loops/functions are extracted. */
struct snd_soc_dai_link { bool ignore_suspend; };
struct snd_soc_pcm_runtime {
    int num_cpus, num_codecs, num_components;
    struct snd_soc_dai *dais[4];
    struct snd_soc_component *components[2];
    struct snd_soc_dai_link *dai_link;
    void *pcm;
};
struct snd_soc_card {
    bool instantiated;
    struct snd_card *snd_card;
    struct snd_soc_dapm_context dapm;
    unsigned int count, component_count;
    struct snd_soc_pcm_runtime *rtds[2];
    struct snd_soc_component *components[2];
    struct list_head list;
    struct mutex mutex;
};
#define for_each_card_rtds(card, rtd) \
    for (unsigned int model_r = 0; model_r < (card)->count && ((rtd) = (card)->rtds[model_r]); model_r++)
#define for_each_rtd_dais(rtd, i, dai) \
    for ((i) = 0; (i) < (rtd)->num_cpus + (rtd)->num_codecs && ((dai) = (rtd)->dais[i]); (i)++)
#define for_each_rtd_components(rtd, i, component) \
    for ((i) = 0; (i) < (rtd)->num_components && ((component) = (rtd)->components[i]); (i)++)
#define for_each_card_components(card, component) \
    for (unsigned int model_c = 0; model_c < (card)->component_count && ((component) = (card)->components[model_c]); model_c++)
#define for_each_pcm_streams(stream) for ((stream) = 0; (stream) < 2; (stream)++)
#define SNDRV_CTL_POWER_D0 0
#define SNDRV_CTL_POWER_D3hot 3
#define SND_SOC_DAPM_STREAM_SUSPEND 1
#define SND_SOC_BIAS_OFF 0
#define SND_SOC_BIAS_STANDBY 1
#define fallthrough __attribute__((fallthrough))
static unsigned int pm_side_effects;
static void *dev_get_drvdata(struct device *dev) { return dev->data; }
static void snd_power_wait(void *card, int state) { (void)card; (void)state; pm_side_effects++; }
static void snd_power_change_state(void *card, int state) { (void)card; (void)state; pm_side_effects++; }
static bool snd_soc_dai_stream_active(struct snd_soc_dai *d, int direction) { (void)d; (void)direction; return true; }
static void snd_soc_dai_digital_mute(struct snd_soc_dai *d, int mute, int direction) { (void)d; (void)mute; (void)direction; pm_side_effects++; }
static void snd_pcm_suspend_all(void *pcm) { (void)pcm; pm_side_effects++; }
static void snd_soc_card_suspend_pre(struct snd_soc_card *card) { (void)card; pm_side_effects++; }
static void snd_soc_flush_all_delayed_work(struct snd_soc_card *card) { (void)card; pm_side_effects++; }
static void snd_soc_dapm_stream_event(struct snd_soc_pcm_runtime *rtd, int direction, int event) { (void)rtd; (void)direction; (void)event; pm_side_effects++; }
static void dapm_mark_endpoints_dirty(struct snd_soc_card *card) { (void)card; pm_side_effects++; }
static void snd_soc_dapm_sync(struct snd_soc_dapm_context *dapm) { (void)dapm; pm_side_effects++; }
static struct snd_soc_dapm_context *snd_soc_component_get_dapm(struct snd_soc_component *c) { return &c->dapm; }
static bool snd_soc_component_is_suspended(struct snd_soc_component *c) { return c->suspended; }
static int snd_soc_dapm_get_bias_level(struct snd_soc_dapm_context *dapm) { return dapm->bias; }
static void snd_soc_component_suspend(struct snd_soc_component *c) { c->suspended = true; pm_side_effects++; }
static void regcache_mark_dirty(struct regmap *map) { (void)map; pm_side_effects++; }
static int pinctrl_pm_select_sleep_state(struct device *dev) { (void)dev; pm_side_effects++; return 0; }
static void snd_soc_card_suspend_post(struct snd_soc_card *card) { (void)card; pm_side_effects++; }
static void snd_soc_dapm_shutdown(struct snd_soc_card *card) { (void)card; pm_side_effects++; }

/* Finite CPU field shape, not kernel layout/ABI. */
struct rk_i2s_tdm_dev {
    pthread_mutex_t lock;
    struct snd_soc_dai_params_state shared_params;
    bool shared_params_enabled, shutting_down, configuring, format_pm_release;
    bool stop_proven, power_transition, irq_live, irq_drained, mclks_enabled;
    unsigned int started;
    int runtime_error, irq;
    struct device *dev;
    struct regmap *regmap;
    struct clk *mclk_tx, *mclk_rx;
};
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; pthread_mutex_lock(lock); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); pthread_mutex_unlock(lock); } while (0)
static unsigned int cpu_side_effects;
static void synchronize_irq(int irq) { (void)irq; cpu_side_effects++; }
static void regcache_cache_only(struct regmap *map, bool value) { (void)map; (void)value; cpu_side_effects++; }
static int pinctrl_pm_select_idle_state(struct device *dev) { (void)dev; cpu_side_effects++; return 0; }
static int i2s_checked_error_locked(struct rk_i2s_tdm_dev *cpu, int error)
{ if (!cpu->runtime_error) cpu->runtime_error = error; return error; }
