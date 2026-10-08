/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Fake kernel boundaries only; driver functions and private structure are extracted. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#define EPROBE_DEFER 517
#define BIT(n) (1U << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define DBG(...) do { } while (0)
#define dev_err(...) do { } while (0)
#define dev_info(...) do { } while (0)
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p) || IS_ERR(p))
#define GPIOD_OUT_LOW 0
#define GFP_KERNEL 0
#define OUT_VOLUME 3
#define CAPTURE_VOLUME 0
#define RK817_CODEC_ALL 0
#define SND_SOC_DAIFMT_MASTER_MASK 0xf000
#define SND_SOC_DAIFMT_CBS_CFS 0x4000
#define SND_SOC_DAIFMT_CBM_CFM 0x1000

struct device_node { int dummy; };
struct device { struct device *parent; struct device_node *of_node; void *data; };
struct platform_device { struct device dev; };
struct regmap { int dummy; };
struct clk { int dummy; };
struct gpio_desc { int dummy; };
struct mutex { int initialized; };
struct rk808 { void *i2c; struct regmap *regmap; };
struct snd_soc_component { struct device *dev; void *data; struct regmap *regmap; };
struct snd_soc_dai { struct snd_soc_component *component; };
static int rk817_snd_path_controls[3];
static int soc_codec_dev_rk817;
static int rk817_dai[2];
static int rk817_codec_regmap_config;
struct reg_default { unsigned int reg; unsigned int def; };

static struct {
    int read_fail, read_errno, read_count;
    int write_fail, write_errno, write_count;
    unsigned int regs[32], vals[32], read_regs[8];
    int clk_error, clk_refs, clk_calls, clk_disables;
    int controls_error, controls_calls;
    int mutex_live, mutex_inits, mutex_destroys;
    int map_init, map_frees, map_attached, power_down;
    int hp_error, spk_error, hp_calls, spk_calls, gpio_flags_bad;
    int node_missing, node_refs, node_puts;
    int update_error, update_count, update_reg, update_mask, update_val;
    int alloc_error, map_error, getclk_error, register_error, register_calls;
    int map_allocs, map_live, parent_maps, getclk_calls, action_error;
    int action_count, action_owner_bad, release_order, unregister_order, map_release_order;
    int property_values, chip_ver, chip_name;
} f;
static struct regmap map;
static struct clk clock_stub;
static struct gpio_desc hp_gpio, spk_gpio;
static struct device_node child_node;
static void *allocated_priv;
static void (*actions[4])(void *);
static void *action_data[4];

static void *snd_soc_component_get_drvdata(struct snd_soc_component *c) { return c->data; }
static void snd_soc_component_init_regmap(struct snd_soc_component *c, struct regmap *m)
{
    c->regmap = m;
    f.map_attached++;
    f.map_init++;
}
/* This is the actual API's ownership effect, not a harmless detach. */
static void snd_soc_component_exit_regmap(struct snd_soc_component *c)
{
    f.map_frees++;
    c->regmap = NULL;
    f.map_attached--;
}
static int regmap_read(struct regmap *m, unsigned int reg, unsigned int *value)
{
    f.read_regs[f.read_count++] = reg;
    if (f.read_count == f.read_fail)
        return f.read_errno;
    *value = reg == 0xed ? (unsigned int)f.chip_name : (unsigned int)f.chip_ver;
    return 0;
}
static unsigned int snd_soc_component_read(struct snd_soc_component *c, unsigned int reg)
{
    unsigned int value = 0;
    int ret = regmap_read(c->regmap, reg, &value);
    return ret < 0 ? (unsigned int)ret : value;
}
static int snd_soc_component_write(struct snd_soc_component *c, unsigned int reg, unsigned int value)
{
    f.regs[f.write_count] = reg;
    f.vals[f.write_count++] = value;
    return f.write_count == f.write_fail ? f.write_errno : 0;
}
static int snd_soc_component_update_bits(struct snd_soc_component *c, unsigned int reg,
                                          unsigned int mask, unsigned int value)
{
    f.update_count++;
    f.update_reg = reg;
    f.update_mask = mask;
    f.update_val = value;
    return f.update_error;
}
static int clk_prepare_enable(struct clk *c)
{
    f.clk_calls++;
    if (f.clk_error)
        return f.clk_error;
    f.clk_refs++;
    return 0;
}
static void clk_disable_unprepare(struct clk *c) { f.clk_refs--; f.clk_disables++; }
static void mutex_init(struct mutex *m) { m->initialized = 1; f.mutex_live++; f.mutex_inits++; }
static void mutex_destroy(struct mutex *m) { m->initialized = 0; f.mutex_live--; f.mutex_destroys++; }
static int snd_soc_add_component_controls(struct snd_soc_component *c, const void *v, unsigned int n)
{
    f.controls_calls++;
    if (n != 3)
        abort();
    return f.controls_error;
}
static int rk817_codec_power_down(struct snd_soc_component *c, unsigned int mask)
{
    f.power_down++;
    return 0;
}
static void mdelay(unsigned int n) { }
static struct device_node *of_get_child_by_name(struct device_node *parent, const char *name)
{
    if (f.node_missing)
        return NULL;
    f.node_refs++;
    return &child_node;
}
static void of_node_put(struct device_node *node) { f.node_refs--; f.node_puts++; }
static struct gpio_desc *devm_gpiod_get_optional(struct device *dev, const char *name, int flags)
{
    int error;
    if (flags != GPIOD_OUT_LOW)
        f.gpio_flags_bad++;
    if (!strcmp(name, "hp-ctl")) {
        f.hp_calls++;
        error = f.hp_error;
        return error ? ERR_PTR(error) : (f.property_values ? &hp_gpio : NULL);
    }
    f.spk_calls++;
    error = f.spk_error;
    return error ? ERR_PTR(error) : (f.property_values ? &spk_gpio : NULL);
}
static int desc_to_gpio(struct gpio_desc *d) { return 0; }
static int of_property_read_u32(struct device_node *n, const char *name, void *out)
{
    if (!f.property_values)
        return -EINVAL;
    unsigned int value = 1;
    if (strstr(name, "spk-mute"))
        value = 12;
    if (strstr(name, "hp-mute"))
        value = 30;
    memcpy(out, &value, sizeof(value));
    return 0;
}
static bool of_property_read_bool(struct device_node *n, const char *name) { return f.property_values != 0; }
static void *dev_get_drvdata(struct device *d) { return d->data; }
static void *devm_kzalloc(struct device *d, size_t size, int flags)
{
    if (f.alloc_error)
        return NULL;
    allocated_priv = calloc(1, size);
    return allocated_priv;
}
static void platform_set_drvdata(struct platform_device *p, void *data) { p->dev.data = data; }
static struct regmap *devm_regmap_init_i2c(void *i2c, const void *config)
{
    f.map_allocs++;
    if (!f.map_error) {
        f.map_live++;
        f.parent_maps++;
    }
    return f.map_error ? ERR_PTR(f.map_error) : &map;
}
static struct regmap *regmap_init_i2c(void *i2c, const void *config)
{
    f.map_allocs++;
    if (!f.map_error)
        f.map_live++;
    return f.map_error ? ERR_PTR(f.map_error) : &map;
}
static void regmap_exit(struct regmap *m)
{
    f.map_frees++;
    f.map_live--;
    f.map_release_order = ++f.release_order;
}
static int devm_add_action_or_reset(struct device *d, void (*action)(void *), void *data)
{
    if (!d->parent || data != &map)
        f.action_owner_bad++;
    if (f.action_error) {
        action(data);
        return f.action_error;
    }
    actions[f.action_count] = action;
    action_data[f.action_count++] = data;
    return 0;
}
static void fake_component_unregister(void *data) { f.unregister_order = ++f.release_order; }
static void release_child_devres(void)
{
    while (f.action_count) {
        int index = --f.action_count;
        actions[index](action_data[index]);
    }
}
static struct clk *devm_clk_get(struct device *d, const char *name)
{
    f.getclk_calls++;
    return f.getclk_error ? ERR_PTR(f.getclk_error) : &clock_stub;
}
static int devm_snd_soc_register_component(struct device *d, const void *driver, const void *dai, int n)
{
    f.register_calls++;
    if (n != 2)
        abort();
    if (!f.register_error) {
        actions[f.action_count] = fake_component_unregister;
        action_data[f.action_count++] = d;
    }
    return f.register_error;
}
