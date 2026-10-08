#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the actual PCM helper main; only external device boundaries are wrapped."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "pcm-config.c"
UAPI = ROOT / "third_party/linux-rk3588/include/uapi/sound/asound.h"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
EXPECTED_UAPI = "138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447"
IDENTITY = "fe410000.i2s-rk817-hifi rk817-hifi-0"
MARKER = "PCM_CONFIGURATION_VERIFIED_NO_START"

WRAPPERS = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include ALSA_LOCKED_UAPI
extern int pcm_config_main(int argc, char **argv);
extern int __real_sigemptyset(sigset_t *set);
extern int __real_sigaddset(sigset_t *set, int signum);
extern int __real_sigprocmask(int how, const sigset_t *set, sigset_t *old);
extern int __real_sigaction(int signum, const struct sigaction *action, struct sigaction *old);
extern unsigned int __real_alarm(unsigned int seconds);
extern int __real_printf(const char *format, ...);
extern int __real_puts(const char *text);
static const char *scenario;
static const char *events[64];
static unsigned int count, violations, empty_calls, opens, refines, statuses, free_calls, markers;
static int card, stream, ctl = 20, pcm = 21, ctl_closed, pcm_closed, configured;

static int is(const char *name) { return !strcmp(scenario, name); }
static void event(const char *name)
{
    if (count < 64) events[count++] = name;
    else violations++;
}
static int inject(const char *name)
{
    if (is("double-status-free-close")) {
        if (!strcmp(name, "status-setup")) { errno = ENOSPC; return -1; }
        if (!strcmp(name, "free")) { errno = EIO; return -1; }
        if (!strcmp(name, "pcm-close")) { errno = EBADF; return -1; }
    }
    if (is("double-info-close") || is("double-card-close") || is("double-free-close")) {
        const char *first = is("double-info-close") ? "pcm-info" : is("double-card-close") ? "card-info" : "free";
        const char *last = is("double-card-close") ? "ctl-close" : "pcm-close";
        if (!strcmp(name, first)) { errno = ENOSPC; return -1; }
        if (!strcmp(name, last)) { errno = EBADF; return -1; }
    }
    char wanted[64];
    snprintf(wanted, sizeof(wanted), "fail_%s", name);
    if (is(wanted)) { errno = EIO; return -1; }
    snprintf(wanted, sizeof(wanted), "eintr_%s", name);
    if (is(wanted)) { errno = EINTR; return -1; }
    snprintf(wanted, sizeof(wanted), "positive_%s", name);
    return is(wanted) ? 1 : 0;
}
int __wrap_sigemptyset(sigset_t *set)
{
    const char *name = empty_calls++ == 0 ? "empty-timeout" : "empty-unblock";
    event(name);
    if (inject(name)) return -1;
    return __real_sigemptyset(set);
}
int __wrap_sigaddset(sigset_t *set, int signum)
{
    event("add-alarm");
    violations += signum != SIGALRM;
    if (inject("add-alarm")) return -1;
    return __real_sigaddset(set, signum);
}
int __wrap_sigaction(int signum, const struct sigaction *action, struct sigaction *old)
{
    event("action");
    violations += signum != SIGALRM || !action || action->sa_handler != SIG_DFL ||
        action->sa_flags != 0 || old != NULL;
    if (inject("action")) return -1;
    return __real_sigaction(signum, action, old);
}
int __wrap_sigprocmask(int how, const sigset_t *set, sigset_t *old)
{
    event("unblock");
    violations += how != SIG_UNBLOCK || !set || sigismember(set, SIGALRM) != 1 || old != NULL;
    if (inject("unblock")) return -1;
    return __real_sigprocmask(how, set, old);
}
unsigned int __wrap_alarm(unsigned int seconds)
{
    event(seconds == 5 ? "alarm5" : "alarm0");
    violations += seconds != 5 && seconds != 0;
    if (seconds == 0) violations += (opens >= 1 && !ctl_closed && !is("fail_ctl-open") && !is("eintr_ctl-open")) ||
        (opens >= 2 && !pcm_closed && !is("fail_pcm-open") && !is("eintr_pcm-open"));
    return __real_alarm(seconds);
}
int __wrap_open(const char *path, int flags, ...)
{
    char wanted[64];
    const char *name = opens++ == 0 ? "ctl-open" : "pcm-open";
    event(name);
    if (opens == 1) snprintf(wanted, sizeof(wanted), "/dev/snd/controlC%d", card);
    else snprintf(wanted, sizeof(wanted), "/dev/snd/pcmC%dD0%c", card, stream ? 'c' : 'p');
    violations += opens > 2 || strcmp(path, wanted) || flags != (O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    if (opens == 2) violations += !ctl_closed;
    if (inject(name)) return -1;
    return opens == 1 ? ctl : pcm;
}
int __wrap_fstat(int fd, struct stat *st)
{
    const char *name = fd == ctl ? "ctl-stat" : "pcm-stat";
    event(name);
    violations += fd != ctl && fd != pcm;
    int result = inject(name);
    if (result) return result;
    memset(st, 0, sizeof(*st));
    st->st_mode = S_IFCHR | 0600;
    /* Dynamic minors are intentional; the PCM INFO contract establishes identity. */
    st->st_rdev = makedev(116, fd == ctl ? 6 : stream ? 5 : 4);
    if (is("high-dynamic-minor")) st->st_rdev = makedev(116, 197);
    if (is(fd == ctl ? "ctl-regular" : "pcm-regular")) st->st_mode = S_IFREG | 0600;
    if (is(fd == ctl ? "ctl-major" : "pcm-major")) st->st_rdev = makedev(1, 4);
    return 0;
}
static int single_mask(const struct snd_mask *mask, unsigned int bit)
{
    for (unsigned int i = 0; i < 8; i++) {
        if (mask->bits[i] != (i == bit / 32 ? (1U << (bit % 32)) : 0U)) return 0;
    }
    return 1;
}
static int interval_is(const struct snd_pcm_hw_params *p, int param, unsigned int value)
{
    const struct snd_interval *i = &p->intervals[param - 8];
    return i->min == value && i->max == value && !i->openmin && !i->openmax && !i->empty;
}
static void check_any(const struct snd_pcm_hw_params *p)
{
    violations += p->flags != 0 || p->rmask != ~0U || p->cmask != 0;
    for (int m = 0; m < 3; m++) for (int n = 0; n < 8; n++) violations += p->masks[m].bits[n] != UINT_MAX;
    for (int n = 0; n < 12; n++) violations += p->intervals[n].min != 0 || p->intervals[n].max != UINT_MAX ||
        p->intervals[n].empty || p->intervals[n].openmin || p->intervals[n].openmax || p->intervals[n].integer;
}
static void check_exact(const struct snd_pcm_hw_params *p)
{
    violations += p->flags != 0 || p->rmask != ~0U || !single_mask(&p->masks[0], 3) ||
        !single_mask(&p->masks[1], 2) || !single_mask(&p->masks[2], 0);
    static const int params[] = {8, 9, 10, 11, 13, 14, 15, 17, 18};
    static const unsigned int values[] = {16, 32, 2, 48000, 256, 1024, 4, 1024, 4096};
    for (unsigned int n = 0; n < sizeof(params) / sizeof(params[0]); n++) violations += !interval_is(p, params[n], values[n]);
}
static void full_caps(struct snd_pcm_hw_params *p)
{
    memset(p, 0, sizeof(*p));
    p->masks[0].bits[0] = (1U << 0) | (1U << 3);
    p->masks[1].bits[0] = (1U << 2) | (1U << 10);
    p->masks[2].bits[0] = 1;
    static const unsigned int lower[] = {16, 16, 1, 8000, 1, 32, 64, 2, 1, 64, 128, 0};
    static const unsigned int upper[] = {32, 256, 8, 192000, UINT_MAX, 4096, 16384, 16, UINT_MAX, 8192, 32768, UINT_MAX};
    for (int n = 0; n < 12; n++) { p->intervals[n].min = lower[n]; p->intervals[n].max = upper[n]; }
    p->info = SNDRV_PCM_INFO_INTERLEAVED;
    if (is("unsupported-access")) p->masks[0].bits[0] &= ~(1U << 3);
    if (is("unsupported-format")) p->masks[1].bits[0] &= ~(1U << 2);
    if (is("unsupported-subformat")) p->masks[2].bits[0] = 2;
    if (is("caps-empty-mask")) memset(&p->masks[1], 0, sizeof(p->masks[1]));
    if (is("caps-empty-interval")) p->intervals[3].empty = 1;
    if (is("caps-inverted-interval")) p->intervals[3].min = 192001;
    if (is("caps-open-singleton")) { p->intervals[3].min = p->intervals[3].max = 48000; p->intervals[3].openmin = 1; }
    if (is("unsupported-rate")) p->intervals[3].max = 44100;
    if (is("unsupported-channels")) p->intervals[2].min = 4;
    if (is("unsupported-period")) p->intervals[5].min = 512;
    if (is("unsupported-periods")) p->intervals[7].min = 8;
    if (is("unsupported-buffer")) p->intervals[9].min = 2048;
    if (is("open-rate-boundary")) { p->intervals[3].min = 48000; p->intervals[3].openmin = 1; }
    if (is("open-buffer-boundary")) { p->intervals[9].max = 1024; p->intervals[9].openmax = 1; }
}
static void alter_exact(struct snd_pcm_hw_params *p, const char *stage)
{
    char name[80];
    static const char *labels[] = {"sample", "frame", "channels", "rate", "period", "period-bytes", "periods", "buffer", "buffer-bytes"};
    static const int params[] = {8, 9, 10, 11, 13, 14, 15, 17, 18};
    for (int n = 0; n < 9; n++) {
        snprintf(name, sizeof(name), "%s-%s-drift", stage, labels[n]);
        if (is(name)) p->intervals[params[n] - 8].min = p->intervals[params[n] - 8].max = 1;
    }
    static const char *masks[] = {"access", "format", "subformat"};
    for (int n = 0; n < 3; n++) {
        snprintf(name, sizeof(name), "%s-%s-drift", stage, masks[n]);
        if (is(name)) { memset(&p->masks[n], 0, sizeof(p->masks[n])); p->masks[n].bits[0] = 2; }
        snprintf(name, sizeof(name), "%s-%s-extra", stage, masks[n]);
        if (is(name)) p->masks[n].bits[0] |= 1U << 30;
    }
    snprintf(name, sizeof(name), "%s-open-interval", stage);
    if (is(name)) p->intervals[3].openmax = 1;
    snprintf(name, sizeof(name), "%s-empty-interval", stage);
    if (is(name)) p->intervals[3].empty = 1;
    snprintf(name, sizeof(name), "%s-wide-interval", stage);
    if (is(name)) p->intervals[3].max++;
    p->rmask = 0;
    p->cmask = 0;
    p->rate_num = 48000;
    p->rate_den = 1;
}
int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list ap;
    va_start(ap, request);
    void *arg = request == SNDRV_PCM_IOCTL_HW_FREE ? NULL : va_arg(ap, void *);
    va_end(ap);
    const char *name = NULL;
    if (request == SNDRV_CTL_IOCTL_CARD_INFO) name = "card-info";
    else if (request == SNDRV_PCM_IOCTL_PVERSION) name = "version";
    else if (request == SNDRV_PCM_IOCTL_INFO) name = "pcm-info";
    else if (request == SNDRV_PCM_IOCTL_HW_REFINE) name = ++refines == 1 ? "refine-full" : "refine-exact";
    else if (request == SNDRV_PCM_IOCTL_HW_PARAMS) name = "params";
    else if (request == SNDRV_PCM_IOCTL_STATUS) name = ++statuses == 1 ? "status-setup" : "status-open";
    else if (request == SNDRV_PCM_IOCTL_HW_FREE) name = "free";
    else { event("FORBIDDEN_IOCTL"); violations++; errno = EPERM; return -1; }
    event(name);
    violations += fd != (request == SNDRV_CTL_IOCTL_CARD_INFO ? ctl : pcm);
    if (request != SNDRV_CTL_IOCTL_CARD_INFO) violations += !ctl_closed;
    if (request == SNDRV_PCM_IOCTL_HW_FREE) { free_calls++; violations += free_calls != 1 || !configured; }
    if (is("deadline") && request == SNDRV_PCM_IOCTL_HW_PARAMS) for (;;) pause();
    int result = inject(name);
    if (result < 0) return result;
    if (request == SNDRV_CTL_IOCTL_CARD_INFO) {
        struct snd_ctl_card_info *i = arg;
        memset(i, 0, sizeof(*i));
        i->card = card;
        memcpy(i->id, "rockchiprk809co", 15);
        if (is("wrong-card-id")) memcpy(i->id, "USB-Audio", 10);
        if (is("wrong-card-number")) i->card++;
        if (is("unterminated-card-id")) memset(i->id, 'x', sizeof(i->id));
        if (is("dirty-card-id-tail")) i->id[15] = 'x';
    } else if (request == SNDRV_PCM_IOCTL_PVERSION) {
        *(int *)arg = SNDRV_PCM_VERSION;
        if (is("version-old")) *(int *)arg = SNDRV_PROTOCOL_VERSION(1, 0, 0);
        if (is("version-new-major")) *(int *)arg = SNDRV_PROTOCOL_VERSION(3, 0, 0);
        if (is("version-future-minor")) *(int *)arg = SNDRV_PROTOCOL_VERSION(2, 1, 0);
        if (is("version-negative")) *(int *)arg = -1;
    } else if (request == SNDRV_PCM_IOCTL_INFO) {
        struct snd_pcm_info *i = arg;
        memset(i, 0, sizeof(*i));
        i->card = card; i->stream = stream;
        memcpy(i->id, "fe410000.i2s-rk817-hifi rk817-hifi-0", sizeof("fe410000.i2s-rk817-hifi rk817-hifi-0"));
        memcpy(i->name, i->id, sizeof(i->id));
        memcpy(i->subname, "subdevice #0", 13);
        i->subdevices_count = 1;
        if (is("info-card-drift")) i->card++;
        if (is("info-device-drift")) i->device = 1;
        if (is("info-subdevice-drift")) i->subdevice = 1;
        if (is("info-stream-drift")) i->stream = !stream;
        if (is("info-id-wrong")) i->id[0] = 'x';
        if (is("info-name-wrong")) i->name[0] = 'x';
        if (is("info-id-short-link")) memcpy(i->id, "fe410000.i2s-rk817-hifi", sizeof("fe410000.i2s-rk817-hifi"));
        if (is("info-id-unterminated")) memset(i->id, 'x', sizeof(i->id));
        if (is("info-name-unterminated")) memset(i->name, 'x', sizeof(i->name));
        if (is("info-id-control-char")) i->id[3] = '\n';
        if (is("info-name-control-char")) i->name[3] = '\n';
        if (is("info-subname-unterminated")) memset(i->subname, 'x', sizeof(i->subname));
        if (is("info-many-subdevices")) i->subdevices_count = 2;
        if (is("info-no-subdevices")) i->subdevices_count = 0;
        if (is("info-invalid-avail")) i->subdevices_avail = 2;
    } else if (request == SNDRV_PCM_IOCTL_HW_REFINE) {
        struct snd_pcm_hw_params *p = arg;
        if (refines == 1) { check_any(p); full_caps(p); }
        else { check_exact(p); alter_exact(p, "exact"); }
    } else if (request == SNDRV_PCM_IOCTL_HW_PARAMS) {
        struct snd_pcm_hw_params *p = arg;
        check_exact(p);
        configured = 1;
        alter_exact(p, "params");
    } else if (request == SNDRV_PCM_IOCTL_STATUS) {
        struct snd_pcm_status *s = arg;
        memset(s, 0, sizeof(*s));
        s->state = statuses == 1 ? SNDRV_PCM_STATE_SETUP : SNDRV_PCM_STATE_OPEN;
        if (is("setup-running") && statuses == 1) s->state = SNDRV_PCM_STATE_RUNNING;
        if (is("setup-prepared") && statuses == 1) s->state = SNDRV_PCM_STATE_PREPARED;
        if (is("setup-open") && statuses == 1) s->state = SNDRV_PCM_STATE_OPEN;
        if (is("setup-appl-pointer") && statuses == 1) s->appl_ptr = 1;
        if (is("setup-hw-pointer") && statuses == 1) s->hw_ptr = 1;
        if (is("free-not-open") && statuses == 2) s->state = SNDRV_PCM_STATE_SETUP;
        if (is("open-retains-pointers") && statuses == 2) { s->appl_ptr = 17; s->hw_ptr = 23; }
    } else if (request == SNDRV_PCM_IOCTL_HW_FREE) configured = 0;
    return result;
}
int __wrap_close(int fd)
{
    const char *name = fd == ctl ? "ctl-close" : "pcm-close";
    event(name);
    violations += fd != ctl && fd != pcm;
    if (fd == ctl) { violations += ctl_closed; ctl_closed = 1; }
    if (fd == pcm) { violations += pcm_closed || (configured && !free_calls); pcm_closed = 1; }
    return inject(name);
}
static int report(const char *format, va_list ap)
{
    char buffer[2048];
    int len = vsnprintf(buffer, sizeof(buffer), format, ap);
    if (len < 0 || len >= (int)sizeof(buffer)) { violations++; return -1; }
    if (strstr(buffer, "PCM_CAP")) violations += refines != 1 || configured;
    if (strstr(buffer, "PCM_CONFIGURATION_VERIFIED_NO_START")) {
        markers++;
        violations += !ctl_closed || !pcm_closed || !free_calls;
    }
    return __real_printf("%s", buffer);
}
int __wrap_printf(const char *format, ...)
{
    va_list ap;
    va_start(ap, format);
    int result = report(format, ap);
    va_end(ap);
    return result;
}
int __wrap___printf_chk(int flag, const char *format, ...)
{
    (void)flag;
    va_list ap;
    va_start(ap, format);
    int result = report(format, ap);
    va_end(ap);
    return result;
}
int __wrap_puts(const char *text)
{
    if (!strcmp(text, "PCM_CONFIGURATION_VERIFIED_NO_START")) {
        markers++;
        violations += !ctl_closed || !pcm_closed || !free_calls;
    }
    return __real_puts(text);
}
static int forbidden(const char *name) { event(name); violations++; errno = EPERM; return -1; }
int __wrap_openat(int dirfd, const char *path, int flags, ...) { (void)dirfd; (void)path; (void)flags; return forbidden("openat"); }
ssize_t __wrap_read(int fd, void *p, size_t n) { (void)fd; (void)p; (void)n; return forbidden("read"); }
ssize_t __wrap_write(int fd, const void *p, size_t n) { (void)fd; (void)p; (void)n; return forbidden("write"); }
ssize_t __wrap_pread(int fd, void *p, size_t n, off_t off) { (void)fd; (void)p; (void)n; (void)off; return forbidden("pread"); }
ssize_t __wrap_pwrite(int fd, const void *p, size_t n, off_t off) { (void)fd; (void)p; (void)n; (void)off; return forbidden("pwrite"); }
long __wrap_syscall(long number, ...) { (void)number; return forbidden("syscall"); }
int __wrap_system(const char *p) { (void)p; return forbidden("system"); }
int __wrap_fcntl(int fd, int command, ...) { (void)fd; (void)command; return forbidden("fcntl"); }
void *__wrap_mmap(void *p, size_t n, int prot, int flags, int fd, off_t off) { (void)p; (void)n; (void)prot; (void)flags; (void)fd; (void)off; forbidden("mmap"); return MAP_FAILED; }
int main(int argc, char **argv)
{
    scenario = getenv("PCM_SCENARIO");
    if (!scenario) scenario = "success";
    card = argc == 6 && strlen(argv[3]) == 1 && argv[3][0] >= '0' && argv[3][0] <= '7' ? argv[3][0] - '0' : 2;
    stream = argc == 6 && !strcmp(argv[5], "capture");
    if (is("fd-zero")) { ctl = 0; pcm = 1; }
    if (is("deadline") || is("inherited-block")) {
        sigset_t mask;
        __real_sigemptyset(&mask);
        __real_sigaddset(&mask, SIGALRM);
        __real_sigprocmask(SIG_BLOCK, &mask, NULL);
        struct sigaction action;
        memset(&action, 0, sizeof(action));
        action.sa_handler = SIG_IGN;
        __real_sigemptyset(&action.sa_mask);
        __real_sigaction(SIGALRM, &action, NULL);
    }
    int result = pcm_config_main(argc, argv);
    fprintf(stderr, "PCM_TEST_RESULT={\"events\":[");
    for (unsigned int n = 0; n < count; n++) fprintf(stderr, "%s\"%s\"", n ? "," : "", events[n]);
    fprintf(stderr, "],\"violations\":%u,\"markers\":%u,\"configured\":%d}\n", violations, markers, configured);
    return result;
}
'''

SIGNALS = ["empty-timeout", "action", "empty-unblock", "add-alarm", "unblock", "alarm5"]
DEVICE = ["ctl-open", "ctl-stat", "card-info", "ctl-close", "pcm-open", "pcm-stat", "version", "pcm-info", "refine-full", "refine-exact", "params", "status-setup", "free", "status-open", "pcm-close"]
SUCCESS_TRACE = SIGNALS + DEVICE + ["alarm0"]
FORBIDDEN = ["openat", "read", "write", "pread", "pwrite", "syscall", "system", "fcntl", "mmap"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh(path):
    if path.exists() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("Refuse existing or symlink evidence directory")
    if not path.resolve().is_relative_to((HERE / "build").resolve()):
        raise ValueError("Evidence escapes build directory")
    path.mkdir(parents=True)


def failure_trace(stage, positive=False):
    if stage in SIGNALS:
        return SIGNALS[:SIGNALS.index(stage) + 1]
    trace = SIGNALS + DEVICE[:DEVICE.index(stage) + 1]
    if stage in ["ctl-open"]:
        return trace + ["alarm0"]
    if stage in ["ctl-stat", "card-info"]:
        return trace + ["ctl-close", "alarm0"]
    if stage in ["ctl-close", "pcm-open"]:
        return trace + ["alarm0"]
    if stage in ["pcm-stat", "version", "pcm-info", "refine-full", "refine-exact"]:
        return trace + ["pcm-close", "alarm0"]
    if stage == "params":
        return trace + (["free"] if positive else []) + ["pcm-close", "alarm0"]
    if stage == "status-setup":
        return trace + ["free", "pcm-close", "alarm0"]
    if stage in ["free", "status-open"]:
        return trace + ["pcm-close", "alarm0"]
    return trace + ["alarm0"]


def cases():
    # Each literal fixture names a wrong branch, wrong syscall, or missing validation.
    out = []
    valid = ["--configure", "--card", "2", "--stream", "playback"]
    for card in range(8):
        for stream in ["playback", "capture"]:
            out.append((f"card-{card}-{stream}", "success", ["--configure", "--card", str(card), "--stream", stream], True, SUCCESS_TRACE))
    for scenario in ["fd-zero", "high-dynamic-minor", "open-retains-pointers", "inherited-block"]:
        out.append((scenario, scenario, valid, True, SUCCESS_TRACE))
    for stage in SIGNALS[:-1] + DEVICE:
        for prefix in ["fail", "eintr"]:
            out.append((prefix + "_" + stage, prefix + "_" + stage, valid, False, failure_trace(stage)))
    for stage in ["ctl-stat", "card-info", "ctl-close", "pcm-stat", "version", "pcm-info", "refine-full", "refine-exact", "params", "status-setup", "free", "status-open", "pcm-close"]:
        out.append(("positive_" + stage, "positive_" + stage, valid, False, failure_trace(stage, positive=True)))
    for name, stage in [("double-status-free-close", "status-setup"), ("double-info-close", "pcm-info"), ("double-card-close", "card-info"), ("double-free-close", "free")]:
        out.append((name, name, valid, False, failure_trace(stage)))
    invalid_args = [[], ["--help"], ["--configure"], ["--configure", "--card", "2"],
                    ["--inspect", "--card", "2", "--stream", "playback"],
                    ["--configure", "--card", "2", "--stream", "PLAYBACK"],
                    ["--configure", "--card", "2", "--stream", "both"],
                    ["--configure", "--card", "2", "--stream", "capture", "--start"],
                    ["--configure", "--stream", "capture", "--card", "2"]]
    for value in ["", "8", "-1", "99", "02", "+2", "2x", " 2", "2 ", "0/../../x"]:
        invalid_args.append(["--configure", "--card", value, "--stream", "playback"])
    for index, argv in enumerate(invalid_args):
        out.append((f"bad-args-{index}", "bad-args", argv, False, []))
    fixtures = {
        "ctl-stat": ["ctl-regular", "ctl-major"],
        "card-info": ["wrong-card-id", "wrong-card-number", "unterminated-card-id", "dirty-card-id-tail"],
        "pcm-stat": ["pcm-regular", "pcm-major"],
        "version": ["version-old", "version-new-major", "version-future-minor", "version-negative"],
        "pcm-info": ["info-card-drift", "info-device-drift", "info-subdevice-drift", "info-stream-drift", "info-id-wrong", "info-name-wrong", "info-id-short-link", "info-id-unterminated", "info-name-unterminated", "info-id-control-char", "info-name-control-char", "info-subname-unterminated", "info-many-subdevices", "info-no-subdevices", "info-invalid-avail"],
        "refine-full": ["unsupported-access", "unsupported-format", "unsupported-subformat", "caps-empty-mask", "caps-empty-interval", "caps-inverted-interval", "caps-open-singleton", "unsupported-rate", "unsupported-channels", "unsupported-period", "unsupported-periods", "unsupported-buffer", "open-rate-boundary", "open-buffer-boundary"],
        "status-setup": ["setup-running", "setup-prepared", "setup-open", "setup-appl-pointer", "setup-hw-pointer"],
        "status-open": ["free-not-open"],
    }
    for stage, names in fixtures.items():
        for name in names:
            out.append((name, name, valid, False, failure_trace(stage)))
    for label, stage in [("exact", "refine-exact"), ("params", "params")]:
        for field in ["sample", "frame", "channels", "rate", "period", "period-bytes", "periods", "buffer", "buffer-bytes", "access", "format", "subformat"]:
            name = f"{label}-{field}-drift"
            out.append((name, name, valid, False, failure_trace(stage, positive=stage == "params")))
        for field in ["access", "format", "subformat"]:
            name = f"{label}-{field}-extra"
            out.append((name, name, valid, False, failure_trace(stage, positive=stage == "params")))
        for issue in ["open-interval", "empty-interval", "wide-interval"]:
            name = f"{label}-{issue}"
            out.append((name, name, valid, False, failure_trace(stage, positive=stage == "params")))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--missing-baseline", action="store_true")
    parser.add_argument("--aarch64-qemu", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    if sha(UAPI) != EXPECTED_UAPI:
        raise ValueError("Locked ALSA UAPI differs")
    output = HERE / "build" / ("pcm-tests-" + args.label)
    fresh(output)
    source = output / "source-under-test.c"
    source.write_text("int main(int argc, char **argv) { (void)argc; (void)argv; return 0; }\n") if args.missing_baseline else source.write_bytes(SOURCE.read_bytes())
    # Compile a symlink to the captured genuine translation unit; no source rewriting.
    compiled_source = output / "compile-source.c"
    compiled_source.symlink_to(source.name)
    wrapper = output / "wrappers.c"
    wrapper.write_text(WRAPPERS)
    compiler = "aarch64-linux-gnu-gcc" if args.aarch64_qemu else "gcc"
    flags = ['-DALSA_LOCKED_UAPI="' + str(UAPI) + '"', "-D__user=", "-D__force="]
    obj = output / "pcm-config.o"
    compile_argv = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-builtin", "-fno-ident", *flags, "-Dmain=pcm_config_main", "-c", str(compiled_source), "-o", str(obj)]
    result = subprocess.run(compile_argv, capture_output=True, text=True, timeout=30)
    (output / "compile.txt").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError("Actual C main compile failed: " + result.stderr)
    executable = output / "wrapped-pcm-config"
    wrapped = ["sigemptyset", "sigaddset", "sigaction", "sigprocmask", "alarm", "open", "fstat", "ioctl", "close", "printf", "__printf_chk", "puts", *FORBIDDEN]
    link_argv = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags, str(wrapper), str(obj), *["-Wl,--wrap=" + name for name in wrapped], "-o", str(executable)]
    if args.aarch64_qemu:
        link_argv.insert(1, "-static")
    result = subprocess.run(link_argv, capture_output=True, text=True, timeout=30)
    (output / "link.txt").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError("Wrapped main link failed: " + result.stderr)
    prefix = [str(QEMU)] if args.aarch64_qemu else []
    evidence = []
    for name, scenario, argv, success, trace in cases():
        result = subprocess.run([*prefix, str(executable), *argv], capture_output=True, text=True, timeout=10, env=dict(os.environ, PCM_SCENARIO=scenario))
        match = re.search(r"PCM_TEST_RESULT=(\{.*\})\n$", result.stderr)
        observed = json.loads(match[1]) if match else {}
        passed = result.returncode == (0 if success else 2) and observed.get("events") == trace and observed.get("violations") == 0 and observed.get("markers") == int(success)
        if success:
            card, stream = int(argv[2]), argv[4]
            passed = passed and f"PCM_INFO card={card} device=0 subdevice=0 stream={stream} id={IDENTITY} name={IDENTITY}\n" in result.stdout
            passed = passed and "PCM_CONFIG format=S16_LE access=RW_INTERLEAVED rate=48000 channels=2 period_size=256 periods=4 buffer_size=1024\n" in result.stdout and result.stdout.endswith(MARKER + "\n")
            passed = passed and result.stdout.count("PCM_CAP_MASK ") == 3 and result.stdout.count("PCM_CAP_INTERVAL ") == 12
            passed = passed and "PCM_STATE configured=SETUP appl_ptr=0 hw_ptr=0\n" in result.stdout and "PCM_STATE freed=OPEN\n" in result.stdout
        else:
            passed = passed and MARKER not in result.stdout and bool(result.stderr.split("PCM_TEST_RESULT=", 1)[0].strip())
            if not trace:
                passed = passed and "usage:" in result.stderr and not result.stdout
            if scenario.startswith("fail_") and scenario[5:] in DEVICE:
                passed = passed and "(errno=5)" in result.stderr
            if scenario.startswith("eintr_") and scenario[6:] in DEVICE:
                passed = passed and "(errno=4)" in result.stderr
            if scenario.startswith("double-"):
                passed = passed and "(errno=28)" in result.stderr and "(errno=9)" not in result.stderr
        evidence.append({"name": name, "scenario": scenario, "arguments": argv, "passed": passed, "expected_trace": trace, "expected_exit_code": 0 if success else 2, "exit_code": result.returncode, "observed": observed, "stdout": result.stdout, "stderr": result.stderr})
    started = time.monotonic()
    try:
        result = subprocess.run([*prefix, str(executable), "--configure", "--card", "2", "--stream", "playback"], capture_output=True, text=True, timeout=8, env=dict(os.environ, PCM_SCENARIO="deadline"))
        elapsed = time.monotonic() - started
        passed = result.returncode == -signal.SIGALRM and 4.5 <= elapsed <= 8 and MARKER not in result.stdout
        evidence.append({"name": "actual-default-SIGALRM-deadline-inherited-block-and-ignore", "passed": passed, "exit_code": result.returncode, "elapsed_seconds": elapsed, "stdout": result.stdout, "stderr": result.stderr})
    except subprocess.TimeoutExpired:
        evidence.append({"name": "actual-default-SIGALRM-deadline-inherited-block-and-ignore", "passed": False, "external_test_deadline_expired": True, "elapsed_seconds": time.monotonic() - started})
    record = {"source_sha256": sha(source), "test_script_sha256": sha(Path(__file__)), "wrapper_sha256": sha(wrapper), "executable_sha256": sha(executable), "compile_argv": compile_argv, "link_argv": link_argv, "locked_uapi_sha256": sha(UAPI), "cases": evidence, "failures": sum(not c["passed"] for c in evidence), "negative_control": args.missing_baseline, "target": "AArch64 QEMU user with wrapped device calls" if args.aarch64_qemu else "host x86_64 wrapped device calls", "qemu_sha256": sha(QEMU) if args.aarch64_qemu else None, "device_calls_wrapped": wrapped, "board_tested": False, "real_alsa_device_access": False}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    for case in evidence:
        print(case["name"] + " " + ("PASS" if case["passed"] else "FAIL"))
    print("TOTAL_CASES=" + str(len(evidence)))
    print("TOTAL_FAILURES=" + str(record["failures"]))
    raise SystemExit(int(record["failures"] != 0))


if __name__ == "__main__":
    main()
