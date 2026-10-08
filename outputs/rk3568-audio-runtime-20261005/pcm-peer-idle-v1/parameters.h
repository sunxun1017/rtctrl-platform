/* SPDX-License-Identifier: MIT */
/* RK809 PCM parameters only: never prepare/start, transfer frames, or change controls. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#ifdef ALSA_LOCKED_UAPI
#include ALSA_LOCKED_UAPI
#else
#include <sound/asound.h>
#endif

_Static_assert(sizeof(void *) == 8 && sizeof(long) == 8 && sizeof(time_t) == 8,
               "native 64-bit ABI required");
_Static_assert(sizeof(struct snd_ctl_card_info) == 376, "CARD_INFO ABI");
_Static_assert(sizeof(struct snd_pcm_info) == 288, "PCM INFO ABI");
_Static_assert(offsetof(struct snd_pcm_info, id) == 16, "PCM INFO id offset");
_Static_assert(offsetof(struct snd_pcm_info, name) == 80, "PCM INFO name offset");
_Static_assert(sizeof(struct snd_mask) == 32, "PCM mask ABI");
_Static_assert(sizeof(struct snd_interval) == 12, "PCM interval ABI");
_Static_assert(sizeof(struct snd_pcm_hw_params) == 608, "PCM HW_PARAMS ABI");
_Static_assert(offsetof(struct snd_pcm_hw_params, masks) == 4, "PCM masks offset");
_Static_assert(offsetof(struct snd_pcm_hw_params, intervals) == 260, "PCM intervals offset");
_Static_assert(offsetof(struct snd_pcm_hw_params, rmask) == 512, "PCM rmask offset");
_Static_assert(offsetof(struct snd_pcm_hw_params, fifo_size) == 536, "PCM fifo_size offset");
_Static_assert(sizeof(struct snd_pcm_status) == 152, "PCM STATUS ABI");
_Static_assert(offsetof(struct snd_pcm_status, appl_ptr) == 40, "PCM STATUS appl_ptr offset");
_Static_assert(offsetof(struct snd_pcm_status, hw_ptr) == 48, "PCM STATUS hw_ptr offset");
_Static_assert(SNDRV_CTL_IOCTL_CARD_INFO == 0x81785501UL, "CARD_INFO ioctl");
_Static_assert(SNDRV_PCM_IOCTL_PVERSION == 0x80044100UL, "PCM PVERSION ioctl");
_Static_assert(SNDRV_PCM_IOCTL_INFO == 0x81204101UL, "PCM INFO ioctl");
_Static_assert(SNDRV_PCM_IOCTL_HW_REFINE == 0xc2604110UL, "PCM HW_REFINE ioctl");
_Static_assert(SNDRV_PCM_IOCTL_HW_PARAMS == 0xc2604111UL, "PCM HW_PARAMS ioctl");
_Static_assert(SNDRV_PCM_IOCTL_HW_FREE == 0x00004112UL, "PCM HW_FREE ioctl");
_Static_assert(SNDRV_PCM_IOCTL_STATUS == 0x80984120UL, "PCM STATUS ioctl");

static const char pcm_identity[] = "fe410000.i2s-rk817-hifi rk817-hifi-0";
static const int exact_params[] = {
    SNDRV_PCM_HW_PARAM_SAMPLE_BITS, SNDRV_PCM_HW_PARAM_FRAME_BITS,
    SNDRV_PCM_HW_PARAM_CHANNELS, SNDRV_PCM_HW_PARAM_RATE, SNDRV_PCM_HW_PARAM_PERIOD_SIZE,
    SNDRV_PCM_HW_PARAM_PERIOD_BYTES, SNDRV_PCM_HW_PARAM_PERIODS,
    SNDRV_PCM_HW_PARAM_BUFFER_SIZE, SNDRV_PCM_HW_PARAM_BUFFER_BYTES
};
static const unsigned int exact_values[] = {16, 32, 2, 48000, 256, 1024, 4, 1024, 4096};
static const unsigned int exact_masks[] = {
    SNDRV_PCM_ACCESS_RW_INTERLEAVED, SNDRV_PCM_FORMAT_S16_LE, SNDRV_PCM_SUBFORMAT_STD
};

static int text_valid(const unsigned char *text, size_t length, int allow_empty)
{
    for (size_t i = 0; i < length; i++) {
        if (!text[i]) return i != 0 || allow_empty;
        if (text[i] < 0x20 || text[i] > 0x7e) return 0;
    }
    return 0;
}

static int pcm_info_valid(const struct snd_pcm_info *info, int card, int stream)
{
    /* simple-card.c names the link CPU-codec. soc-pcm.c appends codec DAI and index.
     * soc-generic-dmaengine-pcm.c copies that complete id into name. */
    return info->card == card && info->device == 0 && info->subdevice == 0 &&
           info->stream == stream && info->subdevices_count == 1 &&
           info->subdevices_avail <= 1 && text_valid(info->id, sizeof(info->id), 0) &&
           text_valid(info->name, sizeof(info->name), 0) &&
           text_valid(info->subname, sizeof(info->subname), 1) &&
           !strcmp((const char *)info->id, pcm_identity) &&
           !strcmp((const char *)info->name, pcm_identity);
}

static void params_any(struct snd_pcm_hw_params *params)
{
    memset(params, 0, sizeof(*params));
    for (unsigned int m = 0; m < 3; m++) {
        for (unsigned int i = 0; i < 8; i++) params->masks[m].bits[i] = UINT_MAX;
    }
    for (unsigned int i = 0; i < 12; i++) params->intervals[i].max = UINT_MAX;
    params->rmask = ~0U;
}

static void params_exact(struct snd_pcm_hw_params *params)
{
    params_any(params);
    for (unsigned int m = 0; m < 3; m++) {
        memset(&params->masks[m], 0, sizeof(params->masks[m]));
        params->masks[m].bits[exact_masks[m] / 32] = 1U << (exact_masks[m] % 32);
    }
    for (unsigned int i = 0; i < sizeof(exact_params) / sizeof(exact_params[0]); i++) {
        struct snd_interval *interval = &params->intervals[exact_params[i] - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
        interval->min = interval->max = exact_values[i];
        interval->integer = 1;
    }
}

static int interval_contains(const struct snd_interval *interval, unsigned int value)
{
    return !interval->empty && interval->min <= value && interval->max >= value &&
           !(interval->openmin && interval->min == value) &&
           !(interval->openmax && interval->max == value);
}

static int caps_valid(const struct snd_pcm_hw_params *params)
{
    for (unsigned int m = 0; m < 3; m++) {
        unsigned int any = 0;
        for (unsigned int i = 0; i < 8; i++) any |= params->masks[m].bits[i];
        if (!any) return 0;
    }
    for (unsigned int i = 0; i < 12; i++) {
        const struct snd_interval *interval = &params->intervals[i];
        if (interval->empty || interval->min > interval->max ||
            (interval->min == interval->max && (interval->openmin || interval->openmax))) return 0;
    }
    return 1;
}

static int caps_allow_exact(const struct snd_pcm_hw_params *params)
{
    for (unsigned int m = 0; m < 3; m++) {
        if (!(params->masks[m].bits[exact_masks[m] / 32] & (1U << (exact_masks[m] % 32)))) return 0;
    }
    for (unsigned int i = 0; i < sizeof(exact_params) / sizeof(exact_params[0]); i++) {
        if (!interval_contains(&params->intervals[exact_params[i] - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL], exact_values[i])) return 0;
    }
    return 1;
}

static int exact_valid(const struct snd_pcm_hw_params *params)
{
    for (unsigned int m = 0; m < 3; m++) {
        for (unsigned int i = 0; i < 8; i++) {
            const unsigned int expected = i == exact_masks[m] / 32 ? 1U << (exact_masks[m] % 32) : 0;
            if (params->masks[m].bits[i] != expected) return 0;
        }
    }
    for (unsigned int i = 0; i < sizeof(exact_params) / sizeof(exact_params[0]); i++) {
        const struct snd_interval *interval = &params->intervals[exact_params[i] - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
        if (interval->min != exact_values[i] || interval->max != exact_values[i] ||
            interval->openmin || interval->openmax || interval->empty) return 0;
    }
    return 1;
}

