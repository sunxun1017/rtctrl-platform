#ifndef TEST_PARAMS_SHIM_H
#define TEST_PARAMS_SHIM_H
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#define __iomem
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#define __user
#include "asound.h"
#define BIT(n) (1U << (n))
#define GENMASK(h, l) (((~0U) << (l)) & ((~0U) >> (31 - (h))))
#define CONFIG_NO_GKI 1
#define SNDRV_MASK_SIZE (SNDRV_MASK_MAX / 32)
#define __force
#define __ffs(x) __builtin_ctz(x)
#define READ_ONCE(x) __atomic_load_n(&(x), __ATOMIC_ACQUIRE)
#define WRITE_ONCE(x, v) __atomic_store_n(&(x), (v), __ATOMIC_RELEASE)
#define DIV_ROUND_CLOSEST(x, d) (((x) + (d) / 2) / (d))
#define MAXBURST_PER_FIFO 8
#define CH_GRP_MAX 4
#define QUIRK_ALWAYS_ON BIT(0)
#define QUIRK_HDMI_PATH BIT(1)
#include "rockchip_i2s_tdm.h"
#include "actual-formats.h"
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint64_t dma_addr_t;
enum dma_slave_buswidth { DMA_SLAVE_BUSWIDTH_UNDEFINED, DMA_SLAVE_BUSWIDTH_1_BYTE, DMA_SLAVE_BUSWIDTH_2_BYTES, DMA_SLAVE_BUSWIDTH_4_BYTES = 4 };
typedef struct { int counter; } atomic_t;
static int atomic_read(const atomic_t *v) { return v->counter; }
typedef pthread_mutex_t spinlock_t;
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; pthread_mutex_lock(lock); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); pthread_mutex_unlock(lock); } while (0)
struct device { void *data; int usage; };
struct clk { unsigned long rate; struct clk *parent; };
struct regmap { unsigned int hw[64]; unsigned int cache[64]; };
struct list_head { struct list_head *next, *prev; };
struct snd_pcm_substream { int stream; long wait_time; };
struct snd_soc_dai;
struct rk_i2s_tdm_dev;
struct snd_pcm_hw_params;
static int fault_at, operations, reads, writes, clock_calls, pm_error;
static const int injected_errno = -EREMOTEIO;
static int fault_operation(void) { return ++operations == fault_at ? injected_errno : 0; }
static void *dev_get_drvdata(struct device *dev) { return dev->data; }
static int pm_runtime_get_sync(struct device *dev) { dev->usage++; return pm_error; }
static int pm_runtime_put(struct device *dev) { dev->usage--; return 0; }
static void pm_runtime_put_noidle(struct device *dev) { dev->usage--; }
static int regmap_read(struct regmap *map, unsigned int reg, unsigned int *value)
{
    int ret = fault_operation();
    reads++;
    if (!ret) *value = map->cache[reg / 4];
    return ret;
}
static int regmap_update_bits(struct regmap *map, unsigned int reg, unsigned int mask, unsigned int value)
{
    unsigned int changed = (map->cache[reg / 4] & ~mask) | (value & mask);
    int ret = fault_operation();
    writes++;
    map->cache[reg / 4] = changed;
    if (!ret) map->hw[reg / 4] = changed;
    return ret;
}
static int clk_set_rate(struct clk *clk, unsigned long rate)
{
    int ret = fault_operation();
    clock_calls++;
    if (!ret) clk->rate = rate;
    return ret;
}
static unsigned long clk_get_rate(struct clk *clk) { return clk->rate; }
static struct clk *clk_get_parent(struct clk *clk) { return clk->parent; }
static bool clk_has_parent(struct clk *clk, struct clk *parent) { return true; }
static int clk_set_parent(struct clk *clk, struct clk *parent)
{
    int ret = fault_operation();
    clock_calls++;
    if (!ret) clk->parent = parent;
    return ret;
}
#define dev_dbg(...) ((void)0)
#define dev_err(...) ((void)0)
static void rockchip_i2s_tdm_trcm_pause(struct snd_pcm_substream *ss, struct rk_i2s_tdm_dev *dev) { }
static void rockchip_i2s_tdm_trcm_resume(struct snd_pcm_substream *ss, struct rk_i2s_tdm_dev *dev) { }
static int rockchip_i2s_tdm_calibrate_mclk(struct rk_i2s_tdm_dev *dev, struct snd_pcm_substream *ss, unsigned int rate) { return 0; }
static int rockchip_i2s_tdm_params(struct snd_pcm_substream *ss, struct snd_soc_dai *dai, unsigned int bclk, unsigned int lrck, unsigned int fmt) { return 0; }
static int rockchip_i2s_io_multiplex(struct snd_pcm_substream *ss, struct snd_soc_dai *dai) { return 0; }
#endif
