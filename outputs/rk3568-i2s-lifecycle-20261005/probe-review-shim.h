#define regmap_read baseline_regmap_read
#define regmap_update_bits baseline_regmap_update_bits
#define regmap_write_bits baseline_regmap_write_bits
#define regmap_write baseline_regmap_write
#define clk_prepare_enable baseline_clk_prepare_enable
#define clk_disable_unprepare baseline_clk_disable_unprepare
#define pm_runtime_get_sync baseline_pm_runtime_get_sync
#define pm_runtime_put baseline_pm_runtime_put
#define pm_runtime_put_noidle baseline_pm_runtime_put_noidle
#define pm_runtime_disable baseline_pm_runtime_disable
#include "baseline-lifecycle-shim.h"
#undef regmap_read
#undef regmap_update_bits
#undef regmap_write_bits
#undef regmap_write
#undef clk_prepare_enable
#undef clk_disable_unprepare
#undef pm_runtime_get_sync
#undef pm_runtime_put
#undef pm_runtime_put_noidle
#undef pm_runtime_disable
#undef IS_ERR_OR_NULL
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p) || IS_ERR(p))
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define GFP_KERNEL 0
#define IORESOURCE_MEM 0x200
#define IRQF_SHARED 0x80
#define EPROBE_DEFER 517
#define MAXBURST_PER_FIFO 8
#define SND_SOC_DAIFMT_CBS_CFS 0x4000
#define SND_SOC_DAIFMT_NB_NF 0
#define SND_SOC_DAIFMT_I2S 1
#define SNDRV_PCM_RATE_8000_192000 0xdead
#define SNDRV_PCM_FMTBIT_S8 (1ULL << 0)
#define SNDRV_PCM_FMTBIT_S16_LE (1ULL << 1)
#define SNDRV_PCM_FMTBIT_S20_3LE (1ULL << 2)
#define SNDRV_PCM_FMTBIT_S24_LE (1ULL << 3)
#define SNDRV_PCM_FMTBIT_S32_LE (1ULL << 4)
#define SNDRV_PCM_FMTBIT_IEC958_SUBFRAME_LE (1ULL << 5)
struct device_node { const char *name, *compatible, *extra; unsigned int trcm, bclk; bool missing_trcm, has_bclk; };
struct device_attribute { int unused; };
struct attribute { int unused; };
struct attribute_group { struct attribute **attrs; };
#define sysfs_emit(buf, ...) snprintf(buf, 4096, __VA_ARGS__)
struct snd_kcontrol { struct snd_soc_component *component; };
struct snd_ctl_elem_value { union { struct { unsigned int item[2]; } enumerated; struct { long value[2]; } integer; } value; };
struct snd_kcontrol_new { const char *name; int (*get)(struct snd_kcontrol *, struct snd_ctl_elem_value *); int (*put)(struct snd_kcontrol *, struct snd_ctl_elem_value *); };
struct snd_soc_component_driver { const char *name; int (*trigger)(struct snd_soc_component *, struct snd_pcm_substream *, int); const struct snd_kcontrol_new *controls; unsigned int num_controls; };
struct snd_soc_dai;
struct rk_i2s_tdm_dev;
struct rk_i2s_soc_data;
struct snd_soc_dai_driver { int (*probe)(struct snd_soc_dai *); struct { const char *stream_name; unsigned int channels_min, channels_max, rates; uint64_t formats; } playback, capture; const void *ops; int symmetric_rates; };
struct of_device_id { const char *compatible; const void *data; };
static const struct { const char *quirk; unsigned int id; } of_quirks[] = { { "rockchip,always-on", QUIRK_ALWAYS_ON }, { "rockchip,hdmi-path", QUIRK_HDMI_PATH } };
static const struct of_device_id rockchip_i2s_tdm_match[];
static const int rockchip_i2s_tdm_dai_ops, dconfig, rockchip_i2s_tdm_regmap_config;
static const struct snd_kcontrol_new rockchip_i2s_tdm_compensation_control;
static struct { struct attribute attr; } dev_attr_rk3568_lifecycle_state;
static struct attribute *test_attrs[] = { &dev_attr_rk3568_lifecycle_state.attr, NULL };
static const struct attribute_group i2s_checked_group = { .attrs = test_attrs };
enum { LOOPBACK_MODE_DIS, LOOPBACK_MODE_1, LOOPBACK_MODE_2, LOOPBACK_MODE_2_SWAP };
static int fake_control_get(struct snd_kcontrol *k, struct snd_ctl_elem_value *v) { return 0; }
static int fake_control_put(struct snd_kcontrol *k, struct snd_ctl_elem_value *v) { return 0; }
#define SOC_ENUM(x, e) { .name = (x), .get = fake_control_get, .put = fake_control_put }
#define SOC_ENUM_EXT(x, e, g, p) { .name = (x), .get = (g), .put = (p) }
#define SAI_PCM_WAIT_TIME(x, g, p) SOC_ENUM(x, 0)
static struct snd_soc_component *snd_soc_kcontrol_component(struct snd_kcontrol *k) { return k->component; }
static int snd_soc_add_component_controls(struct snd_soc_component *c, const void *controls, int count) { return 0; }
static int regmap_read(struct regmap *, unsigned int, unsigned int *);
static int regmap_update_bits(struct regmap *, unsigned int, unsigned int, unsigned int);
static int regmap_write_bits(struct regmap *, unsigned int, unsigned int, unsigned int);
static int regmap_write(struct regmap *, unsigned int, unsigned int);
static int clk_prepare_enable(struct clk *);
static void clk_disable_unprepare(struct clk *);
static int pm_runtime_get_sync(struct device *);
static int pm_runtime_put(struct device *);
static void pm_runtime_put_noidle(struct device *);
static void pm_runtime_disable(struct device *);
static int i2s_tdm_runtime_suspend(struct device *);
static int i2s_tdm_runtime_resume(struct device *);
static int rockchip_i2s_tdm_probe(struct platform_device *);
static int rockchip_i2s_tdm_remove(struct platform_device *);
static int i2s_checked_isr(struct rk_i2s_tdm_dev *);
static int i2s_checked_set_fmt(struct rk_i2s_tdm_dev *, struct device *, unsigned int);
static int rockchip_i2s_tdm_startup(struct snd_pcm_substream *, struct snd_soc_dai *);
static void rockchip_i2s_tdm_shutdown(struct snd_pcm_substream *, struct snd_soc_dai *);
static void i2s_checked_probe_clock_release(void *);
static int i2s_checked_component_trigger(struct snd_soc_component *, struct snd_pcm_substream *, int);
static int i2s_checked_prepare(struct snd_pcm_substream *, struct snd_soc_dai *);
static int i2s_checked_trigger(struct rk_i2s_tdm_dev *, int, int);
static const struct rk_i2s_soc_data rk3568_i2s_soc_data;
static unsigned int total, passed;
static void check(const char *name, bool ok) { total++; passed += ok; if (!ok) fprintf(stderr, "FAIL %s\n", name); }
