/* SPDX-License-Identifier: MIT */
#ifndef AUDIO_GUARD_PARSER_H
#define AUDIO_GUARD_PARSER_H
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *const cpu_keys[] = {
    "version", "ready", "error", "owners", "open", "stop_proven", "stop_reads",
    "irq_live", "irq_drained", "mclk_leases", "hclk_lease", "configuring",
    "power_transition", "shutting_down"
};
static const char *const dma_keys[] = {
    "version", "ready", "error", "stop_proven", "stop_reads", "pm_usage",
    "leases", "software", "queued", "descriptors", "allocated"
};

/* The frozen drivers emit these keys in this exact order, with one final LF. */
static int parse_state(const char *text, const char *const *keys, size_t count,
                       uint64_t *values)
{
    const char *cursor = text;
    for (size_t i = 0; i < count; i++) {
        size_t length = strlen(keys[i]);
        if (strncmp(cursor, keys[i], length) || cursor[length] != '=') {
            return 0;
        }
        cursor += length + 1;
        /* Negative errno/counts are a rejection, never unsigned wraparound. */
        if (*cursor < '0' || *cursor > '9' || (*cursor == '0' && cursor[1] >= '0' && cursor[1] <= '9')) {
            return 0;
        }
        errno = 0;
        char *end;
        unsigned long long value = strtoull(cursor, &end, 10);
        if (errno || ((strcmp(keys[i], "stop_reads") || count == 14) && value > UINT_MAX)) {
            return 0;
        }
        values[i] = value;
        if (i + 1 == count) {
            return end[0] == '\n' && end[1] == 0;
        }
        if (*end != ' ') {
            return 0;
        }
        cursor = end + 1;
    }
    return 0;
}

static int cpu_valid(const char *text, unsigned int bound)
{
    uint64_t v[14];
    return parse_state(text, cpu_keys, 14, v) && v[0] == 1 && v[1] == 1 &&
           v[2] == 0 && v[3] == 0 && v[4] == 0 && v[5] == 1 && v[6] > 0 &&
           v[7] == 0 && v[8] == 1 && v[9] == 0 && v[10] == bound &&
           v[11] == 0 && v[12] == 0 && v[13] == 0;
}

static int dma_valid(const char *text, unsigned int allocated)
{
    uint64_t v[11];
    return parse_state(text, dma_keys, 11, v) && v[0] == 1 && v[1] == 1 &&
           v[2] == 0 && v[3] == 1 && v[4] > 0 && v[5] == 0 && v[6] == 0 &&
           v[7] == 0 && v[8] == 0 && v[9] == 0 && v[10] == allocated;
}

static int quarantine_valid(const char *text)
{
    return !strcmp(text, "0\n");
}

static int stable_valid(const char *first, const char *second)
{
    return !strcmp(first, second);
}

static int text_printable(const char *text)
{
    if (!*text) {
        return 0;
    }
    for (; *text; text++) {
        if ((unsigned char)*text < 32 || (unsigned char)*text > 126) {
            return 0;
        }
    }
    return 1;
}

/* Exactly the existing inspector's complete output, then stricter Resume OFF. */
static int inspect_valid(char *text, unsigned int card)
{
    static const char *const names[] = {"Playback Path", "Capture MIC Path", "Resume Path"};
    static const char *const labels[] = {"OFF", "MIC OFF", "OFF"};
    char *cursor = text;
    char *line = strsep(&cursor, "\n");
    unsigned int actual_card, count;
    int end = 0;
    char canonical[1024];
    if (!line || sscanf(line, "ALSA_CARD card=%u id=rockchiprk809co controls=%u%n",
                        &actual_card, &count, &end) != 2 || line[end] ||
        actual_card != card || count < 3 || count > 64) {
        return 0;
    }
    snprintf(canonical, sizeof(canonical), "ALSA_CARD card=%u id=rockchiprk809co controls=%u", actual_card, count);
    if (strcmp(line, canonical)) {
        return 0;
    }
    unsigned int ids[64], target_ids[3] = {0};
    for (unsigned int i = 0; i < count; i++) {
        unsigned int iface, device, subdevice, index;
        end = 0;
        line = strsep(&cursor, "\n");
        if (!line || sscanf(line, "ALSA_LIST numid=%u iface=%u device=%u subdevice=%u index=%u name=%n",
                            &ids[i], &iface, &device, &subdevice, &index, &end) != 5 ||
            !end || !ids[i] || ids[i] > 65535 || iface > 6 || !text_printable(line + end)) {
            return 0;
        }
        snprintf(canonical, sizeof(canonical), "ALSA_LIST numid=%u iface=%u device=%u subdevice=%u index=%u name=%s",
                 ids[i], iface, device, subdevice, index, line + end);
        if (strcmp(line, canonical)) {
            return 0;
        }
        for (unsigned int j = 0; j < i; j++) {
            if (ids[j] == ids[i]) {
                return 0;
            }
        }
        for (unsigned int t = 0; t < 3; t++) {
            if (!strcmp(line + end, names[t])) {
                if (target_ids[t] || iface != 2 || device || subdevice || index) {
                    return 0;
                }
                target_ids[t] = ids[i];
            }
        }
    }
    for (unsigned int t = 0; t < 3; t++) {
        unsigned int id, items, value;
        end = 0;
        line = strsep(&cursor, "\n");
        if (!line || !target_ids[t] ||
            sscanf(line, "ALSA_CONTROL numid=%u name=%n", &id, &end) != 1 || !end ||
            id != target_ids[t] || strncmp(line + end, names[t], strlen(names[t]))) {
            return 0;
        }
        const char *tail = line + end + strlen(names[t]);
        end = 0;
        if (sscanf(tail, " items=%u value=%u label=%n", &items, &value, &end) != 2 ||
            !end || !items || items > 64 || value >= items || strcmp(tail + end, labels[t])) {
            return 0;
        }
        snprintf(canonical, sizeof(canonical), "ALSA_CONTROL numid=%u name=%s items=%u value=%u label=%s",
                 id, names[t], items, value, labels[t]);
        if (strcmp(line, canonical)) {
            return 0;
        }
    }
    line = strsep(&cursor, "\n");
    return line && !strcmp(line, "ALSA_CODEC_INTERFACE_VERIFIED") && cursor && !*cursor;
}

static const char *const clock_names[] = {
    "i2s1_mclkout_rx", "clk_i2s1_8ch_rx_src", "clk_i2s1_8ch_rx",
    "mclk_i2s1_8ch_rx", "clk_i2s1_8ch_rx_frac", "clk_i2s1_8ch_tx_src",
    "clk_i2s1_8ch_tx_frac", "clk_i2s1_8ch_tx", "mclk_i2s1_8ch_tx",
    "i2s1_mclkout_tx", "i2s1_mclk_tx_ioe", "i2s1_mclkout", "hclk_i2s1_8ch",
    "i2s1_mclkin_tx", "i2s1_mclkin_rx", "i2s1_mclk_rx_ioe"
};

/* Cached debugfs u32 counts only; never clk_summary/rate/phase callbacks. */
static int clock_valid(char *text, unsigned int bound)
{
    char *cursor = text;
    static const char *const keys[] = {"enable", "prepare", "protect"};
    for (unsigned int i = 0; i < 16; i++) {
        char *line = strsep(&cursor, "\n");
        uint64_t values[3];
        char counts[256];
        size_t length = strlen(clock_names[i]);
        if (!line || strncmp(line, clock_names[i], length) || line[length] != ' ' ||
            snprintf(counts, sizeof(counts), "%s\n", line + length + 1) >= (int)sizeof(counts) ||
            !parse_state(counts, keys, 3, values) || values[2] ||
            values[0] != (i == 12 ? bound : 0) || values[1] != (i == 12 ? bound : 0)) {
            return 0;
        }
    }
    return cursor && !*cursor;
}

/* /proc/devices comes from this kernel's fs/proc/devices.c and chrdev_show.
 * Non-UIO registrations can share a major with disjoint minor ranges (tty).
 * UIO core reserves its entire minor space, so its major must be unique.
 */
static int devices_valid(char *text, unsigned int *uio_major)
{
    char *cursor = text;
    char *line = strsep(&cursor, "\n");
    if (!line || strcmp(line, "Character devices:")) {
        return 0;
    }
    unsigned int character_rows = 0, previous = 0, matches = 0;
    unsigned int counts[512] = {0};
    int block = 0;
    *uio_major = 0;
    while ((line = strsep(&cursor, "\n"))) {
        if (!*line) {
            if (!cursor) {
                return block && character_rows && matches <= 1;
            }
            if (block || !character_rows) {
                return 0;
            }
            line = strsep(&cursor, "\n");
            if (!line || strcmp(line, "Block devices:")) {
                return 0;
            }
            block = 1;
            previous = 0;
            continue;
        }
        unsigned int major_number;
        int end = 0;
        if (sscanf(line, "%u %n", &major_number, &end) != 1 || !end ||
            !major_number || major_number >= 512 || major_number < previous ||
            !text_printable(line + end) || strlen(line + end) > 63) {
            return 0;
        }
        char canonical[128];
        snprintf(canonical, sizeof(canonical), "%3u %s", major_number, line + end);
        if (strcmp(line, canonical)) {
            return 0;
        }
        previous = major_number;
        if (!block) {
            character_rows++;
            counts[major_number]++;
            if (!strcmp(line + end, "uio")) {
                if (++matches != 1 || counts[major_number] != 1) {
                    return 0;
                }
                *uio_major = major_number;
            }
            if (*uio_major && counts[*uio_major] != 1) {
                return 0;
            }
        }
    }
    /* The kernel always emits a final LF; partial/truncated data is rejected. */
    return 0;
}

/* Shared by real /proc scanner and host FD models; no pathname-only bypass. */
static int related_fd(unsigned int character, unsigned int major_number,
                      unsigned int minor_number, const char *target, unsigned int uio_major)
{
    return (character && (major_number == 116 || major_number == 14 ||
                         (uio_major && major_number == uio_major) ||
                         (major_number == 1 && (minor_number == 1 || minor_number == 2)))) ||
           !strncmp(target, "/dev/snd/", 9) || !strncmp(target, "/dev/uio", 8) ||
           !strcmp(target, "/dev/mem") || !strcmp(target, "/dev/kmem");
}
#endif
