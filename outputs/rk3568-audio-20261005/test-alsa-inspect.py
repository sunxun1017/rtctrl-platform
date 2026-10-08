#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the actual C main with fixed ALSA fixtures and intercepted device calls."""
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
SOURCE = HERE / "alsa-inspect.c"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
WRAPPERS = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <sound/asound.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/uio.h>
#include <unistd.h>

extern int inspect_main(int argc, char **argv);
extern int __real_puts(const char *s);
extern unsigned int __real_alarm(unsigned int seconds);
extern int __real_sigaction(int signum, const struct sigaction *action, struct sigaction *old);
static const char *scenario;
static int selected_card = 2;
static int opened, stated, cards, lists, infos, reads, closed, reports, markers, violations;
static int signal_set, timer_set, timer_cancelled;
static unsigned int next_item[3], info_done[3];
static int next_read;
static struct snd_ctl_elem_id fixture[64];
static unsigned int fixture_count;
static struct snd_ctl_elem_id *list_pointer;

static int is(const char *name)
{
    return strcmp(scenario, name) == 0;
}
static int forbidden(void)
{
    violations++;
    errno = EPERM;
    return -1;
}
int __wrap_sigaction(int signum, const struct sigaction *action, struct sigaction *old)
{
    signal_set++;
    violations += signal_set != 1 || opened || signum != SIGALRM || !action ||
        action->sa_handler != SIG_DFL || action->sa_flags != 0 || old != NULL;
    if (is("signal-error")) { errno = EINVAL; return -1; }
    return is("timer-expiration") ? __real_sigaction(signum, action, old) : 0;
}
unsigned int __wrap_alarm(unsigned int seconds)
{
    if (seconds == 5) {
        timer_set++;
        violations += signal_set != 1 || timer_set != 1 || opened;
    } else if (seconds == 0) {
        timer_cancelled++;
        violations += timer_set != 1 || timer_cancelled != 1 || (opened && !closed && !is("open-error"));
    } else {
        violations++;
    }
    return is("timer-expiration") ? __real_alarm(seconds) : 0;
}
int __wrap_openat(int dirfd, const char *path, int flags, ...)
{
    (void)dirfd; (void)path; (void)flags;
    return forbidden();
}
ssize_t __wrap_read(int fd, void *buffer, size_t length)
{
    (void)fd; (void)buffer; (void)length;
    return forbidden();
}
ssize_t __wrap_write(int fd, const void *buffer, size_t length)
{
    (void)fd; (void)buffer; (void)length;
    return forbidden();
}
ssize_t __wrap_writev(int fd, const struct iovec *vectors, int count)
{
    (void)fd; (void)vectors; (void)count;
    return forbidden();
}
ssize_t __wrap_pread(int fd, void *buffer, size_t length, off_t offset)
{
    (void)fd; (void)buffer; (void)length; (void)offset;
    return forbidden();
}
ssize_t __wrap_pwrite(int fd, const void *buffer, size_t length, off_t offset)
{
    (void)fd; (void)buffer; (void)length; (void)offset;
    return forbidden();
}
int __wrap_fcntl(int fd, int command, ...)
{
    (void)fd; (void)command;
    return forbidden();
}
int __wrap_flock(int fd, int operation)
{
    (void)fd; (void)operation;
    return forbidden();
}
int __wrap_dup(int fd) { (void)fd; return forbidden(); }
int __wrap_dup2(int oldfd, int newfd) { (void)oldfd; (void)newfd; return forbidden(); }
int __wrap_socket(int domain, int type, int protocol)
{
    (void)domain; (void)type; (void)protocol;
    return forbidden();
}
long __wrap_syscall(long number, ...) { (void)number; return forbidden(); }
int __wrap_system(const char *command) { (void)command; return forbidden(); }
void *__wrap_mmap(void *address, size_t length, int prot, int flags, int fd, off_t offset)
{
    (void)address; (void)length; (void)prot; (void)flags; (void)fd; (void)offset;
    forbidden();
    return MAP_FAILED;
}
int __wrap_open(const char *path, int flags, ...)
{
    char expected[64];
    snprintf(expected, sizeof(expected), "/dev/snd/controlC%d", selected_card);
    opened++;
    violations += opened != 1 || signal_set != 1 || timer_set != 1 || timer_cancelled || strcmp(path, expected) ||
        flags != (O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY);
    if (is("open-error")) {
        errno = EACCES;
        return -1;
    }
    if (is("timer-expiration")) {
        for (;;) pause();
    }
    return 71;
}
int __wrap_fstat(int fd, struct stat *st)
{
    stated++;
    violations += fd != 71 || opened != 1 || stated != 1 || !st || cards || closed;
    if (is("stat-error") || is("stat-close-error")) {
        errno = EIO;
        return -1;
    }
    memset(st, 0, sizeof(*st));
    st->st_mode = is("ordinary-file") ? S_IFREG : S_IFCHR;
    st->st_rdev = makedev(is("wrong-major") ? 115 : 116, is("dynamic-minor") ? 231 : 64);
    return 0;
}
static void id(struct snd_ctl_elem_id *value, unsigned int number, const char *name)
{
    memset(value, 0, sizeof(*value));
    value->numid = number;
    value->iface = SNDRV_CTL_ELEM_IFACE_MIXER;
    snprintf((char *)value->name, sizeof(value->name), "%s", name);
}
static void prepare_fixture(void)
{
    fixture_count = is("minimal-two") ? 2 : is("linux-three") ? 3 : is("maximum-list") ? 64 : 5;
    if (fixture_count <= 3) {
        id(&fixture[0], 91, "Playback Path");
        id(&fixture[1], 37, "Capture MIC Path");
        if (fixture_count == 3) {
            id(&fixture[2], 6, "Resume Path");
        }
    } else {
        id(&fixture[0], 7, "I2S Loopback Switch");
        id(&fixture[1], 37, "Capture MIC Path");
        id(&fixture[2], 91, "Playback Path");
        id(&fixture[3], 6, "Resume Path");
        id(&fixture[4], 53, "I2S TX Route");
        for (unsigned int i = 5; i < fixture_count; i++) {
            char name[44];
            snprintf(name, sizeof(name), "I2S extra %u", i);
            id(&fixture[i], 1000 + i, name);
        }
    }
    struct snd_ctl_elem_id *playback = &fixture[fixture_count <= 3 ? 0 : 2];
    struct snd_ctl_elem_id *capture = &fixture[1];
    if (is("dynamic-numids")) {
        for (unsigned int i = 0; i < fixture_count; i++) {
            fixture[i].numid += 211;
        }
    }
    if (is("unknown-nonmixer")) {
        fixture[0].iface = SNDRV_CTL_ELEM_IFACE_PCM;
        fixture[0].device = 17;
        fixture[0].subdevice = 4;
        fixture[0].index = 9;
    }
    if (is("zero-numid")) playback->numid = 0;
    if (is("duplicate-numid")) playback->numid = capture->numid;
    if (is("name-unterminated")) memset(playback->name, 'x', sizeof(playback->name));
    if (is("name-empty")) playback->name[0] = 0;
    if (is("name-newline")) playback->name[0] = '\n';
    if (is("missing-playback")) snprintf((char *)playback->name, sizeof(playback->name), "Other Path");
    if (is("missing-capture")) snprintf((char *)capture->name, sizeof(capture->name), "Other Capture");
    if (is("duplicate-playback")) snprintf((char *)fixture[0].name, sizeof(fixture[0].name), "Playback Path");
    if (is("duplicate-capture")) snprintf((char *)fixture[0].name, sizeof(fixture[0].name), "Capture MIC Path");
    if (is("duplicate-resume")) snprintf((char *)fixture[0].name, sizeof(fixture[0].name), "Resume Path");
    if (is("target-iface")) playback->iface = SNDRV_CTL_ELEM_IFACE_PCM;
    if (is("target-device")) playback->device = 1;
    if (is("target-subdevice")) playback->subdevice = 1;
    if (is("target-index")) playback->index = 1;
    if (is("unknown-invalid-iface")) fixture[0].iface = SNDRV_CTL_ELEM_IFACE_LAST + 1;
}
static int target(const struct snd_ctl_elem_id *value)
{
    static const char *names[3] = {"Playback Path", "Capture MIC Path", "Resume Path"};
    for (int t = 0; t < 3; t++) {
        for (unsigned int i = 0; i < fixture_count; i++) {
            if (!strcmp((char *)fixture[i].name, names[t]) &&
                !memcmp(value, &fixture[i], sizeof(*value))) {
                return t;
            }
        }
    }
    return -1;
}
static unsigned int items(int t) { return t == 0 ? 4 : t == 1 ? 3 : 2; }
static unsigned int off(int t)
{
    return t == 0 ? (is("dynamic-off-labels") ? 1 : 2) : (is("dynamic-off-labels") ? 2 : 1);
}
static const char *label(int t, unsigned int item)
{
    static const char *playback[4] = {"SPK", "HP", "OFF", "RCV"};
    static const char *capture[3] = {"Main Mic", "MIC OFF", "Hands Free"};
    static const char *resume[2] = {"Resume OFF", "Resume ON"};
    if (t == 0) {
        if (is("missing-off")) return item == 2 ? "NO OFF" : playback[item];
        if (is("duplicate-off") && item == 3) return "OFF";
        if (is("dynamic-off-labels") && item == 1) return "OFF";
        if (is("dynamic-off-labels") && item == 2) return "HP";
        return playback[item];
    }
    if (t == 1) {
        if (is("missing-mic-off")) return item == 1 ? "NO MIC OFF" : capture[item];
        if (is("duplicate-mic-off") && item == 2) return "MIC OFF";
        if (is("dynamic-off-labels") && item == 1) return "Hands Free";
        if (is("dynamic-off-labels") && item == 2) return "MIC OFF";
        return capture[item];
    }
    return resume[item];
}
int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list arguments;
    va_start(arguments, request);
    void *argument = va_arg(arguments, void *);
    va_end(arguments);
    if (fd != 71 || !argument || opened != 1 || stated != 1 || closed) return forbidden();
    if (request == SNDRV_CTL_IOCTL_CARD_INFO) {
        cards++;
        if (cards != 1 || lists || infos || reads) return forbidden();
        if (is("card-error") || is("card-interrupted")) {
            errno = is("card-interrupted") ? EINTR : EIO;
            return -1;
        }
        if (is("card-nooutput")) return 0;
        struct snd_ctl_card_info *info = argument;
        memset(info, 0, sizeof(*info));
        info->card = is("wrong-card") ? selected_card + 1 : selected_card;
        memcpy(info->id, "rockchiprk809co", sizeof("rockchiprk809co"));
        memcpy(info->driver, "simple-card", sizeof("simple-card"));
        memcpy(info->name, "rockchip,rk809-codec", sizeof("rockchip,rk809-codec"));
        memcpy(info->longname, "rockchip,rk809-codec", sizeof("rockchip,rk809-codec"));
        memcpy(info->mixername, "rk817-codec", sizeof("rk817-codec"));
        if (is("wrong-id")) info->id[0] = 'x';
        if (is("id-unterminated")) info->id[15] = 'x';
        if (is("driver-unterminated")) memset(info->driver, 'x', sizeof(info->driver));
        if (is("cardname-unterminated")) memset(info->name, 'x', sizeof(info->name));
        if (is("longname-unterminated")) memset(info->longname, 'x', sizeof(info->longname));
        if (is("mixername-unterminated")) memset(info->mixername, 'x', sizeof(info->mixername));
        if (is("components-unterminated")) memset(info->components, 'x', sizeof(info->components));
        return is("card-positive") ? 1 : 0;
    }
    if (request == SNDRV_CTL_IOCTL_ELEM_LIST) {
        lists++;
        if (cards != 1 || lists > 2 || infos || reads) return forbidden();
        struct snd_ctl_elem_list *list = argument;
        if (lists == 1) {
            if (list->offset || list->space || list->pids) return forbidden();
            if (is("list-first-error")) { errno = EIO; return -1; }
            if (is("list-first-nooutput")) return 0;
            list->count = fixture_count;
            list->used = 0;
            if (is("list-count-zero")) list->count = 0;
            if (is("list-count-one")) list->count = 1;
            if (is("list-count-too-large")) list->count = 65;
            if (is("list-first-used")) list->used = 1;
            if (is("list-first-pids")) list->pids = (void *)(uintptr_t)8;
            if (is("list-first-space")) list->space = 1;
            if (is("list-first-offset")) list->offset = 1;
            return is("list-first-positive") ? 1 : 0;
        }
        if (!list->pids || list->offset || list->space != fixture_count ||
            (uintptr_t)list->pids <= UINT32_MAX ||
            (uintptr_t)list->pids % _Alignof(struct snd_ctl_elem_id)) return forbidden();
        list_pointer = list->pids;
        if (is("list-second-error")) { errno = EIO; return -1; }
        if (is("list-second-nooutput")) return 0;
        memcpy(list->pids, fixture, fixture_count * sizeof(fixture[0]));
        list->count = fixture_count;
        list->used = fixture_count;
        if (is("list-unstable-count")) list->count++;
        if (is("list-short-used")) list->used--;
        if (is("list-large-used")) list->used++;
        if (is("list-second-pids")) list->pids++;
        if (is("list-second-space")) list->space--;
        if (is("list-second-offset")) list->offset = 1;
        if (is("list-id-nooutput")) memset(list_pointer, 0xff, fixture_count * sizeof(fixture[0]));
        return is("list-second-positive") ? 1 : 0;
    }
    if (request == SNDRV_CTL_IOCTL_ELEM_INFO) {
        infos++;
        struct snd_ctl_elem_info *info = argument;
        int t = target(&info->id);
        if (lists != 2 || !list_pointer || t < 0 || t != next_read ||
            info->value.enumerated.item != next_item[t] ||
            info->value.enumerated.names_ptr || info->value.enumerated.names_length ||
            next_item[t] >= items(t)) return forbidden();
        unsigned int item = next_item[t]++;
        if (is("info-error")) { errno = EIO; return -1; }
        if (is("info-nooutput")) return 0;
        info->type = SNDRV_CTL_ELEM_TYPE_ENUMERATED;
        info->access = SNDRV_CTL_ELEM_ACCESS_READWRITE;
        info->count = 1;
        info->value.enumerated.items = items(t);
        memset(info->value.enumerated.name, 0, sizeof(info->value.enumerated.name));
        snprintf(info->value.enumerated.name, sizeof(info->value.enumerated.name), "%s", label(t, item));
        if (is("info-id-changed")) info->id.numid++;
        if (is("info-integer")) info->type = SNDRV_CTL_ELEM_TYPE_INTEGER;
        if (is("info-noread")) info->access = SNDRV_CTL_ELEM_ACCESS_WRITE;
        if (is("info-count-zero")) info->count = 0;
        if (is("info-count-two")) info->count = 2;
        if (is("info-items-zero")) info->value.enumerated.items = 0;
        if (is("info-items-too-large")) info->value.enumerated.items = 65;
        if (is("info-items-unstable") && item == 1) info->value.enumerated.items++;
        if (is("info-access-unstable") && item == 1) info->access = SNDRV_CTL_ELEM_ACCESS_READ;
        if (is("info-item-changed")) info->value.enumerated.item++;
        if (is("label-empty")) info->value.enumerated.name[0] = 0;
        if (is("label-unterminated")) memset(info->value.enumerated.name, 'x', sizeof(info->value.enumerated.name));
        if (is("label-newline")) info->value.enumerated.name[0] = '\n';
        if (next_item[t] == items(t)) info_done[t] = 1;
        return is("info-positive") ? 1 : 0;
    }
    if (request == SNDRV_CTL_IOCTL_ELEM_READ) {
        reads++;
        struct snd_ctl_elem_value *value = argument;
        int t = target(&value->id);
        if (t < 0 || t != next_read || !info_done[t] || value->indirect) return forbidden();
        next_read++;
        if (is("read-error")) { errno = EIO; return -1; }
        if (is("read-nooutput")) return 0;
        value->value.enumerated.item[0] = t == 2 ? 1 : off(t);
        if (is("read-outofrange")) value->value.enumerated.item[0] = items(t);
        if (is("playback-nonoff") && t == 0) value->value.enumerated.item[0] = 0;
        if (is("capture-nonoff") && t == 1) value->value.enumerated.item[0] = 0;
        if (is("read-id-changed")) value->id.numid++;
        if (is("read-indirect")) value->indirect = 1;
        return is("read-positive") ? 1 : 0;
    }
    /* WRITE, LOCK, PCM and all other requests are explicit test failures. */
    return forbidden();
}
int __wrap_close(int fd)
{
    closed++;
    violations += fd != 71 || closed != 1 || opened != 1;
    if (is("close-error") || is("stat-close-error")) { errno = EIO; return -1; }
    return 0;
}
static int report(const char *format, va_list arguments)
{
    char text[512];
    int result = vsnprintf(text, sizeof(text), format, arguments);
    reports++;
    violations += closed != 1 || timer_cancelled != 1 || is("close-error") || result < 0 || (size_t)result >= sizeof(text);
    fputs(text, stdout);
    return result;
}
int __wrap_printf(const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    int result = report(format, arguments);
    va_end(arguments);
    return result;
}
int __wrap___printf_chk(int flag, const char *format, ...)
{
    (void)flag;
    va_list arguments;
    va_start(arguments, format);
    int result = report(format, arguments);
    va_end(arguments);
    return result;
}
int __wrap_puts(const char *text)
{
    markers++;
    violations += closed != 1 || timer_cancelled != 1 || is("close-error") || markers != 1 || reports == 0 ||
        strcmp(text, "ALSA_CODEC_INTERFACE_VERIFIED");
    return __real_puts(text);
}
int main(int argc, char **argv)
{
    scenario = getenv("ALSA_SCENARIO");
    if (!scenario) scenario = "success";
    if (argc == 4 && strlen(argv[3]) == 1 && argv[3][0] >= '0' && argv[3][0] <= '7') {
        selected_card = argv[3][0] - '0';
    }
    prepare_fixture();
    int result = inspect_main(argc, argv);
    fprintf(stderr, "WRAP opened=%d stated=%d cards=%d lists=%d infos=%d reads=%d closed=%d reports=%d markers=%d violations=%d signal_set=%d timer_set=%d timer_cancelled=%d\n",
            opened, stated, cards, lists, infos, reads, closed, reports, markers, violations,
            signal_set, timer_set, timer_cancelled);
    return result;
}
'''

BASELINE = r'''
/* A compilable absent-feature baseline, retained as pre-implementation RED evidence. */
#include <stdio.h>
int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    fprintf(stderr, "usage: alsa-inspect --inspect --card N (contract not implemented)\n");
    return 2;
}
'''

FORBIDDEN = ["openat", "read", "write", "writev", "pread", "pwrite", "fcntl", "flock",
             "dup", "dup2", "socket", "syscall", "system", "mmap"]
SUCCESS = ["success", "minimal-two", "linux-three", "maximum-list", "dynamic-minor",
           "dynamic-numids", "dynamic-off-labels", "unknown-nonmixer"]
FAILURE = [
    "open-error", "stat-error", "stat-close-error", "ordinary-file", "wrong-major",
    "card-error", "card-interrupted", "card-nooutput", "card-positive", "wrong-card",
    "wrong-id", "id-unterminated", "driver-unterminated", "cardname-unterminated",
    "longname-unterminated", "mixername-unterminated", "components-unterminated",
    "list-first-error", "list-first-nooutput", "list-first-positive", "list-count-zero",
    "list-count-one", "list-count-too-large", "list-first-used", "list-first-pids",
    "list-first-space", "list-first-offset", "list-second-error", "list-second-nooutput",
    "list-second-positive", "list-unstable-count", "list-short-used", "list-large-used",
    "list-second-pids", "list-second-space", "list-second-offset", "list-id-nooutput",
    "zero-numid", "duplicate-numid", "name-unterminated", "name-empty", "name-newline",
    "missing-playback", "missing-capture", "duplicate-playback", "duplicate-capture",
    "duplicate-resume", "target-iface", "target-device", "target-subdevice", "target-index",
    "unknown-invalid-iface", "info-error", "info-nooutput", "info-positive", "info-id-changed",
    "info-integer", "info-noread", "info-count-zero", "info-count-two", "info-items-zero",
    "info-items-too-large", "info-items-unstable", "info-access-unstable", "info-item-changed",
    "label-empty", "label-unterminated", "label-newline", "missing-off", "duplicate-off",
    "missing-mic-off", "duplicate-mic-off", "read-error", "read-nooutput", "read-positive",
    "read-outofrange", "playback-nonoff", "capture-nonoff", "read-id-changed", "read-indirect",
    "close-error", "signal-error",
]
INVALID_ARGS = [[], ["--help"], ["--inspect"], ["--card", "2", "--inspect"],
                ["--inspect", "--card"], ["--inspect", "--card", "8"],
                ["--inspect", "--card", "-1"], ["--inspect", "--card", "02"],
                ["--inspect", "--card", "+2"], ["--inspect", "--card", "2x"],
                ["--inspect", "--card", ""], ["--inspect", "--card", "2", "extra"],
                ["--write", "--card", "2"], ["--inspect", "/dev/snd/controlC2"],
                ["--inspect", "--card", "/dev/snd/controlC2"]]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, timeout=15, **kwargs)


def fresh(path):
    if path.exists() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("Refuse existing or symlink evidence directory")
    if not path.resolve().is_relative_to((HERE / "build").resolve()):
        raise ValueError("Evidence directory escapes build")
    path.mkdir(parents=True)


def expected_stdout(scenario, card):
    count = 2 if scenario == "minimal-two" else 3 if scenario == "linux-three" else 64 if scenario == "maximum-list" else 5
    if count <= 3:
        ids = [(91, "Playback Path"), (37, "Capture MIC Path")]
        if count == 3:
            ids.append((6, "Resume Path"))
    else:
        ids = [(7, "I2S Loopback Switch"), (37, "Capture MIC Path"), (91, "Playback Path"),
               (6, "Resume Path"), (53, "I2S TX Route")]
        ids.extend((1000 + i, "I2S extra " + str(i)) for i in range(5, count))
    if scenario == "dynamic-numids":
        ids = [(number + 211, name) for number, name in ids]
    lines = [f"ALSA_CARD card={card} id=rockchiprk809co controls={count}"]
    for number, name in ids:
        fields = "iface=3 device=17 subdevice=4 index=9" if scenario == "unknown-nonmixer" and name == "I2S Loopback Switch" else "iface=2 device=0 subdevice=0 index=0"
        lines.append(f"ALSA_LIST numid={number} {fields} name={name}")
    number_by_name = {name: number for number, name in ids}
    playback = 1 if scenario == "dynamic-off-labels" else 2
    capture = 2 if scenario == "dynamic-off-labels" else 1
    lines.append(f"ALSA_CONTROL numid={number_by_name['Playback Path']} name=Playback Path items=4 value={playback} label=OFF")
    lines.append(f"ALSA_CONTROL numid={number_by_name['Capture MIC Path']} name=Capture MIC Path items=3 value={capture} label=MIC OFF")
    if count != 2:
        lines.append(f"ALSA_CONTROL numid={number_by_name['Resume Path']} name=Resume Path items=2 value=1 label=Resume ON")
    lines.append("ALSA_CODEC_INTERFACE_VERIFIED")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--missing-baseline", action="store_true")
    parser.add_argument("--pre-deadline-baseline", action="store_true")
    parser.add_argument("--aarch64-qemu", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    output = HERE / "build" / ("inspect-tests-" + args.label)
    fresh(output)
    wrappers = output / "wrappers.c"
    wrappers.write_text(WRAPPERS)
    source = SOURCE
    if args.missing_baseline:
        source = output / "missing-contract-baseline.c"
        source.write_text(BASELINE)
    elif args.pre_deadline_baseline:
        original = HERE / "build/inspect-tests-red-v3/source-under-test.c"
        original_record = json.loads((original.parent / "result.json").read_text())
        if sha(original) != original_record["source_sha256"] or original_record["failures"] == 0:
            raise ValueError("Pre-deadline original C evidence changed")
        source = output / "source-under-test.c"
        source.write_bytes(original.read_bytes())
    else:
        source = output / "source-under-test.c"
        source.write_bytes(SOURCE.read_bytes())
    compiler = "aarch64-linux-gnu-gcc" if args.aarch64_qemu else "gcc"
    obj = output / "inspect.o"
    compile_argv = [compiler, "-std=c11", "-O2", "-fno-builtin", "-fno-ident", "-Wall", "-Wextra", "-Werror", "-Dmain=inspect_main",
                    "-c", str(source), "-o", str(obj)]
    result = run(compile_argv)
    (output / "compile.txt").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError("Actual C main failed to compile: " + result.stderr)
    executable = output / "wrapped-inspect"
    link_argv = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(wrappers), str(obj),
                 *["-Wl,--wrap=" + name for name in ["open", "fstat", "ioctl", "close", "printf", "__printf_chk", "puts", "alarm", "sigaction", *FORBIDDEN]],
                 "-o", str(executable)]
    if args.aarch64_qemu:
        link_argv.insert(1, "-static")
    result = run(link_argv)
    (output / "link.txt").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError("Wrapped C main failed to link: " + result.stderr)
    prefix = [str(QEMU)] if args.aarch64_qemu else []
    cases = []
    scenarios = [(scenario, ["--inspect", "--card", "2"], scenario in SUCCESS) for scenario in [*SUCCESS, *FAILURE]]
    scenarios.extend(("success", ["--inspect", "--card", str(card)], True) for card in range(8))
    scenarios.extend(("bad-args", arguments, False) for arguments in INVALID_ARGS)
    for scenario, arguments, success in scenarios:
        environment = dict(os.environ, ALSA_SCENARIO=scenario)
        result = run([*prefix, str(executable), *arguments], env=environment)
        match = re.search(r"WRAP opened=(\d+) stated=(\d+) cards=(\d+) lists=(\d+) infos=(\d+) reads=(\d+) closed=(\d+) reports=(\d+) markers=(\d+) violations=(\d+) signal_set=(\d+) timer_set=(\d+) timer_cancelled=(\d+)\n$", result.stderr)
        counts = dict(zip(["opened", "stated", "cards", "lists", "infos", "reads", "closed", "reports", "markers", "violations", "signal_set", "timer_set", "timer_cancelled"], map(int, match.groups()))) if match else {}
        card = int(arguments[-1]) if success else 2
        wanted = expected_stdout(scenario, card) if success else ""
        passed = result.returncode == (0 if success else 2) and result.stdout == wanted and bool(counts) and counts["violations"] == 0
        if counts:
            if scenario == "bad-args":
                passed = passed and all(value == 0 for value in counts.values()) and "usage:" in result.stderr
            elif scenario == "signal-error":
                passed = passed and counts["signal_set"] == 1 and counts["timer_set"] == 0 and counts["timer_cancelled"] == 0 and counts["opened"] == 0 and counts["closed"] == 0
            else:
                passed = passed and counts["opened"] == 1 and counts["closed"] == (0 if scenario == "open-error" else 1)
                passed = passed and counts["signal_set"] == 1 and counts["timer_set"] == 1 and counts["timer_cancelled"] == 1
                if success:
                    controls = 2 if scenario == "minimal-two" else 3
                    passed = passed and counts["cards"] == 1 and counts["lists"] == 2 and counts["infos"] == (7 if controls == 2 else 9) and counts["reads"] == controls and counts["markers"] == 1
                else:
                    passed = passed and counts["reports"] == 0 and counts["markers"] == 0 and bool(result.stderr.split("WRAP ", 1)[0].strip())
        cases.append({"name": scenario + ("-" + repr(arguments) if scenario in ["success", "bad-args"] else ""),
                      "arguments": arguments, "passed": passed, "expected_exit_code": 0 if success else 2,
                      "exit_code": result.returncode, "counts": counts, "stdout": result.stdout, "stderr": result.stderr})
    started = time.monotonic()
    try:
        result = subprocess.run([*prefix, str(executable), "--inspect", "--card", "2"],
                                env=dict(os.environ, ALSA_SCENARIO="timer-expiration"),
                                capture_output=True, text=True, timeout=8)
        elapsed = time.monotonic() - started
        passed = result.returncode == -signal.SIGALRM and not result.stdout and 4.5 <= elapsed <= 8
        cases.append({"name": "actual-default-SIGALRM-deadline", "passed": passed,
                      "exit_code": result.returncode, "elapsed_seconds": elapsed,
                      "stdout": result.stdout, "stderr": result.stderr})
    except subprocess.TimeoutExpired:
        cases.append({"name": "actual-default-SIGALRM-deadline", "passed": False,
                      "elapsed_seconds": time.monotonic() - started, "external_test_deadline_expired": True})
    record = {"source_sha256": sha(source), "test_script_sha256": sha(Path(__file__)),
              "wrapper_sha256": sha(wrappers), "executable_sha256": sha(executable),
              "compile_argv": compile_argv, "link_argv": link_argv, "cases": cases,
              "failures": sum(not case["passed"] for case in cases),
              "negative_control": args.missing_baseline or args.pre_deadline_baseline,
              "negative_control_defect": "ALSA inspection contract absent" if args.missing_baseline else "SIGALRM deadline absent from original C" if args.pre_deadline_baseline else None,
              "target": "AArch64 QEMU user with wrapped device calls" if args.aarch64_qemu else "host x86_64 wrapped device calls",
              "device_calls_wrapped": ["open", "fstat", "ioctl", "close"],
              "timer_calls_wrapped": ["alarm", "sigaction"], "forbidden_calls_wrapped": FORBIDDEN,
              "qemu_sha256": sha(QEMU) if args.aarch64_qemu else None,
              "board_tested": False, "real_alsa_device_access": False}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    for case in cases:
        print(case["name"] + " " + ("PASS" if case["passed"] else "FAIL"))
    print("TOTAL_CASES=" + str(len(cases)))
    print("TOTAL_FAILURES=" + str(record["failures"]))
    raise SystemExit(int(record["failures"] != 0))


if __name__ == "__main__":
    main()
