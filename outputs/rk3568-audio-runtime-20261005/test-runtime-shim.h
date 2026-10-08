/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Only hardware/kernel API boundaries are mocked; real driver bodies are compiled. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define DBG(...) do { } while (0)
#define pr_err(...) do { } while (0)
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
#define SNDRV_PCM_FORMAT_S16_LE 2
#define SNDRV_PCM_FORMAT_S24_LE 6
#define SNDRV_PCM_FORMAT_S32_LE 10
#define SNDRV_PCM_FORMAT_S20_3LE 36
#define SNDRV_PCM_FMTBIT_S16_LE (1ULL << SNDRV_PCM_FORMAT_S16_LE)
#define SNDRV_PCM_FMTBIT_S24_LE (1ULL << SNDRV_PCM_FORMAT_S24_LE)
#define SNDRV_PCM_FMTBIT_S32_LE (1ULL << SNDRV_PCM_FORMAT_S32_LE)
#define SNDRV_PCM_FMTBIT_S20_3LE (1ULL << SNDRV_PCM_FORMAT_S20_3LE)
struct device { int unused; };
struct regmap { int unused; };
struct rk808 { int unused; };
struct clk { int unused; };
struct mutex { int unused; };
struct gpio_desc { int unused; };
struct snd_soc_component { void *data; };
struct snd_soc_dai { struct snd_soc_component *component; };
struct snd_pcm_substream { int stream; };
struct snd_pcm_hw_params { unsigned int rate; int format; };
static unsigned int params_rate(struct snd_pcm_hw_params *p) { return p->rate; }
static int params_format(struct snd_pcm_hw_params *p) { return p->format; }
static void *snd_soc_component_get_drvdata(struct snd_soc_component *c) { return c->data; }
static struct {
    int calls, fail_at, error, update_success;
    unsigned int reg[32], mask[32], value[32];
    char kind[32];
} fault;
static int boundary(char kind, unsigned int reg, unsigned int mask, unsigned int value)
{
    int index = fault.calls++;
    if (index >= 32)
        __builtin_trap();
    fault.kind[index] = kind;
    fault.reg[index] = reg;
    fault.mask[index] = mask;
    fault.value[index] = value;
    return fault.calls == fault.fail_at ? fault.error : (kind == 'u' ? fault.update_success : 0);
}
static int snd_soc_component_write(struct snd_soc_component *c, unsigned int reg, unsigned int value)
{
    return boundary('w', reg, 0, value);
}
static int snd_soc_component_update_bits(struct snd_soc_component *c, unsigned int reg,
                                          unsigned int mask, unsigned int value)
{
    return boundary('u', reg, mask, value);
}
static void usleep_range(unsigned int low, unsigned int high) { }
