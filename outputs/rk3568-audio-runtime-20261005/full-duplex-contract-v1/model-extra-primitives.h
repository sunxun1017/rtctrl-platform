/* SPDX-License-Identifier: MIT */
/* Only kernel API side effects below are modelled; caller functions are extracted. */
#include <stdarg.h>
#define ENOTSUPP 524
#define EPROBE_DEFER 517
#define KERN_ERR ""
#define DBG(...) ((void)0)
#define msecs_to_jiffies(x) (x)
static void model_debug(const char *format, ...) { (void)format; }
#define printk(...) model_debug(__VA_ARGS__)
#define pr_debug(...) model_debug(__VA_ARGS__)
static unsigned int irq_sync_calls;
static unsigned int diagnostics;
static unsigned int child_enable_calls, child_disable_calls;
static int child_refs;
static int model_constraint_error;
static void model_log(const char *format, ...)
{
    (void)format;
    __atomic_add_fetch(&diagnostics, 1, __ATOMIC_RELAXED);
}
#undef dev_err
#define dev_err(dev, ...) model_log(__VA_ARGS__)
static void udelay(unsigned int value) { (void)value; }
static void synchronize_irq(int irq) { (void)irq; irq_sync_calls++; }
static void pm_runtime_mark_last_busy(struct device *dev) { (void)dev; }
static int pm_runtime_put_autosuspend(struct device *dev) { dev->auto_puts++; return pm_runtime_put(dev); }
static unsigned int readl(void *address) { return *(unsigned int *)address; }
static int regmap_write_bits(struct regmap *map, unsigned int reg, unsigned int mask, unsigned int value)
{
    int ret = regmap_update_bits(map, reg, mask, value);
    if (!ret && reg == I2S_CLR) {
        /* Explicit successful hardware self-clear model, never a board proof. */
        map->hw[reg / 4] = map->cache[reg / 4] = 0;
    }
    return ret;
}
#define regmap_read_poll_timeout_atomic(map, reg, value, condition, delay, timeout) \
    ({ int model_ret = regmap_read((map), (reg), &(value)); \
       if (!model_ret && !(condition)) { model_ret = -ETIMEDOUT; } \
       model_ret; })
static void rockchip_i2s_tdm_start(struct rk_i2s_tdm_dev *dev, int stream) { (void)dev; (void)stream; }
static void rockchip_i2s_tdm_stop(struct rk_i2s_tdm_dev *dev, int stream) { (void)dev; (void)stream; }
static int clk_prepare_enable(struct clk *clk)
{
    if (clk) { child_enable_calls++; child_refs++; }
    return 0;
}
static void clk_disable_unprepare(struct clk *clk)
{
    if (clk) { child_disable_calls++; child_refs--; }
}
