#ifndef TEST_LIFECYCLE_SHIM_H
#define TEST_LIFECYCLE_SHIM_H
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#include <setjmp.h>
#define __iomem
#define BIT(n) (1U << (n))
#define GENMASK(h, l) (((~0U) << (l)) & ((~0U) >> (31 - (h))))
#define HAVE_SYNC_RESET 1
#define CH_GRP_MAX 4
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
#define SNDRV_PCM_STREAM_LAST 1
#define SNDRV_PCM_TRIGGER_STOP 0
#define SNDRV_PCM_TRIGGER_START 1
#define SNDRV_PCM_TRIGGER_PAUSE_PUSH 3
#define SNDRV_PCM_TRIGGER_PAUSE_RELEASE 4
#define SNDRV_PCM_TRIGGER_SUSPEND 5
#define SNDRV_PCM_TRIGGER_RESUME 6
#define QUIRK_ALWAYS_ON BIT(0)
#define QUIRK_HDMI_PATH BIT(1)
#define DRV_NAME "rockchip-i2s-tdm"
struct device;
static int rockchip_i2s_tdm_pinctrl_select_clk_state(struct device *dev);
#define fallthrough __attribute__((fallthrough))
#define IS_ALIGNED(x, a) (((x) & ((a) - 1)) == 0)
#define IS_ERR_OR_NULL(x) (!(x))
#define READ_ONCE(x) __atomic_load_n(&(x), __ATOMIC_ACQUIRE)
#define WRITE_ONCE(x, v) __atomic_store_n(&(x), (v), __ATOMIC_RELEASE)
#include "rockchip_i2s_tdm.h"
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint64_t dma_addr_t;
enum dma_slave_buswidth { DMA_SLAVE_BUSWIDTH_UNDEFINED, DMA_SLAVE_BUSWIDTH_1_BYTE, DMA_SLAVE_BUSWIDTH_2_BYTES, DMA_SLAVE_BUSWIDTH_4_BYTES = 4 };
typedef struct { int counter; } atomic_t;
static int atomic_inc_return(atomic_t *v) { return ++v->counter; }
static bool atomic_dec_and_test(atomic_t *v) { return --v->counter == 0; }
typedef pthread_mutex_t spinlock_t;
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; pthread_mutex_lock(lock); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); pthread_mutex_unlock(lock); } while (0)
#define local_irq_save(flags) ((flags) = 0)
#define local_irq_restore(flags) ((void)(flags))
struct device_node;
struct resource { unsigned long start, end; };
struct device { void *data; int usage; bool pm_disabled; bool suspended; struct device_node *of_node; };
struct platform_device { struct device dev; struct resource *resource; };
struct clk { unsigned long rate; int enables; };
struct regmap { unsigned int hw[1024], cache[1024]; bool cache_only; };
struct list_head { struct list_head *next, *prev; };
struct snd_pcm_substream { int stream; long wait_time; };
struct snd_soc_component { struct device *dev; };
static void *snd_soc_component_get_drvdata(struct snd_soc_component *component) { return component->dev->data; }
struct reset_control { int asserted; };
static atomic_int operations;
static int faults[64], polls[4], poll_calls, reset_calls, force_calls, hw_writes;
static bool ignore_xfer_stop;
static int clk_fault, enable_calls, disable_underflows, sync_error, pm_error, pinctrl_error;
static int panic_timeout __attribute__((unused));
static jmp_buf panic_jump;
static bool panic_seen;
static void *dev_get_drvdata(struct device *dev) { return dev->data; }
static int fault_operation(void) { int op = atomic_fetch_add(&operations, 1) + 1; return faults[op % 64]; }
static int regmap_read(struct regmap *map, unsigned int reg, unsigned int *value)
{
    int ret = fault_operation();
    if (!ret) *value = map->cache[reg / 4];
    return ret;
}
static int regmap_update_bits(struct regmap *map, unsigned int reg, unsigned int mask, unsigned int value)
{
    unsigned int changed = (map->cache[reg / 4] & ~mask) | (value & mask);
    int ret = fault_operation();
    bool write = changed != map->cache[reg / 4] || reg == I2S_INTCR || reg == I2S_CLR;
    map->cache[reg / 4] = changed;
    if (write) { hw_writes++; if (!ret) map->hw[reg / 4] = changed; }
    return ret;
}
static int regmap_write_bits(struct regmap *map, unsigned int reg, unsigned int mask, unsigned int value)
{
    unsigned int changed = (map->cache[reg / 4] & ~mask) | (value & mask);
    int ret = fault_operation();
    force_calls++;
    hw_writes++;
    map->cache[reg / 4] = changed;
    if (!ret && !(ignore_xfer_stop && reg == I2S_XFER && !(changed & 3))) map->hw[reg / 4] = changed;
    return ret;
}
static int regmap_write(struct regmap *map, unsigned int reg, unsigned int value)
{ return regmap_write_bits(map, reg, ~0U, value); }
static int test_poll(struct regmap *map, unsigned int reg, unsigned int *value)
{
    int ret = regmap_read(map, reg, value);
    int planned = polls[poll_calls++ % 4];
    if (ret) return ret;
    if (planned) return planned;
    map->cache[reg / 4] = map->hw[reg / 4] = *value = 0;
    return 0;
}
#define regmap_read_poll_timeout_atomic(map, reg, val, condition, delay, timeout) test_poll(map, reg, &(val))
static int reset_control_assert(struct reset_control *rc) { reset_calls++; if (rc) rc->asserted = 1; return 0; }
static int reset_control_deassert(struct reset_control *rc) { reset_calls++; if (rc) rc->asserted = 0; return 0; }
static void writel(unsigned int v, void *addr) { reset_calls++; }
static void writeq(u64 v, void *addr) { reset_calls++; }
static void udelay(unsigned int us) { }
static unsigned int readl(const void *addr) { return *(const unsigned int *)addr; }
static int clk_prepare_enable(struct clk *clk)
{ if (++enable_calls == clk_fault) return -EREMOTEIO; clk->enables++; return 0; }
static void clk_disable_unprepare(struct clk *clk)
{ if (clk->enables <= 0) disable_underflows++; else clk->enables--; }
static void regcache_cache_only(struct regmap *map, bool enabled) { map->cache_only = enabled; }
static void regcache_mark_dirty(struct regmap *map) { }
static int regcache_sync(struct regmap *map) { return sync_error; }
static int pinctrl_pm_select_idle_state(struct device *dev) { return pinctrl_error; }
static int pinctrl_select_state(void *pinctrl, void *state) { return pinctrl_error; }
static int pm_runtime_get_sync(struct device *dev) { dev->usage++; return pm_error; }
static int pm_runtime_put(struct device *dev) { dev->usage--; return 0; }
static void pm_runtime_put_noidle(struct device *dev) { dev->usage--; }
static void pm_runtime_disable(struct device *dev) { dev->pm_disabled = true; }
static bool pm_runtime_status_suspended(struct device *dev) { return dev->suspended; }
static int pm_runtime_force_suspend(struct device *dev) { return pm_error; }
static int pm_runtime_force_resume(struct device *dev) { return pm_error; }
static void __attribute__((noreturn)) panic(const char *fmt, ...)
{ panic_seen = true; longjmp(panic_jump, 1); }
#define dev_dbg(...) ((void)0)
#define dev_warn(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_warn_ratelimited(...) ((void)0)
typedef int irqreturn_t;
#define IRQ_NONE 0
#define IRQ_HANDLED 1
#define msecs_to_jiffies(x) (x)
static int snd_pcm_stop_xrun(struct snd_pcm_substream *substream);
static void synchronize_irq(unsigned int irq);
#endif
