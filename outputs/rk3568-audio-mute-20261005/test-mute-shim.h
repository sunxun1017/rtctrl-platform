/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Test-only API boundary, including cache-before-bus-error behavior. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define BIT(n) (1U << (n))
#define DBG(...) ((void)0)
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
struct device { int unused; };
struct regmap { int unused; };
struct rk808 { int unused; };
struct clk { int unused; };
struct mutex { int unused; };
struct gpio_desc { int id; };
struct snd_soc_component { void *data; };
struct snd_soc_dai { struct snd_soc_component *component; };
static void *snd_soc_component_get_drvdata(struct snd_soc_component *c) { return c->data; }
static int snd_soc_component_write(struct snd_soc_component *c, unsigned int reg, unsigned int value);
static int snd_soc_component_update_bits(struct snd_soc_component *c, unsigned int reg,
                                          unsigned int mask, unsigned int value);
static void usleep_range(unsigned int low, unsigned int high);
static void msleep(unsigned int delay);
static void gpiod_set_value(struct gpio_desc *gpio, int level);
