/* SPDX-License-Identifier: MIT */
#include <setjmp.h>
#define msecs_to_jiffies(x) (x)
struct snd_soc_component { struct device *dev; };
static void *snd_soc_component_get_drvdata(struct snd_soc_component *component) { return component->dev->data; }
static void synchronize_irq(int irq);
static void regcache_cache_only(struct regmap *map, bool only);
static void clk_disable_unprepare(struct clk *clock);
static int pinctrl_pm_select_idle_state(struct device *dev);
static void pm_runtime_disable(struct device *dev);
static int pm_runtime_set_suspended(struct device *dev);
static int i2s_checked_runtime_resume(struct rk_i2s_tdm_dev *info);
static int i2s_checked_stop_locked(struct rk_i2s_tdm_dev *info, int stream, bool force);
static void i2s_checked_failstop(struct rk_i2s_tdm_dev *info, const char *op, int ret);
