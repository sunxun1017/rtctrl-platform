/* SPDX-License-Identifier: MIT */
/* Explicit ALSA syscall boundary model; production source is linked unchanged. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#include "asound-locked.h"

static const char *scenario;
static int stream, state = SNDRV_PCM_STATE_OPEN;
static unsigned int reads, writes, polls, start_calls, drop_calls, free_calls, closes;
static unsigned long queued, received;
static long milliseconds;
static bool event_fired;
static bool baseline;
static bool timer_armed;
static void event(const char *name, long value)
{ fprintf(stderr, "TEST_CALL %s %ld\n", name, value); }
static bool is_case(const char *name) { return !strcmp(scenario, name); }
static int failure(const char *name, int error)
{ if (!is_case(name)) return 0; errno = error; return -1; }
__attribute__((constructor)) static void initialize(void)
{
    scenario = getenv("PCM_TEST_CASE");
    if (!scenario) abort();
    baseline = getenv("PCM_TEST_BASELINE") != NULL;
    if (is_case("real-timer")) {
        signal(SIGALRM, SIG_IGN);
        sigset_t set;
        sigemptyset(&set); sigaddset(&set, SIGALRM);
        sigprocmask(SIG_BLOCK, &set, NULL);
    }
}
int __wrap_open(const char *path, int flags, ...)
{
    int card = -1; char direction = 0;
    if (sscanf(path, "/dev/snd/controlC%d", &card) == 1 && !strstr(path, "pcm")) {
        if (card != (baseline ? 0 : 7) && !(is_case("duplicate-card") && card == 9) && !(is_case("other-control") && card == 0)) { errno = ENOENT; return -1; }
        event("open-control", card);
        if (failure("open-control", EACCES)) return -1;
        if (!(flags & O_NONBLOCK) || !(flags & O_NOFOLLOW) || !(flags & O_CLOEXEC)) abort();
        return 100 + card;
    }
    if (sscanf(path, "/dev/snd/pcmC%dD0%c", &card, &direction) == 2) {
        stream = direction == 'c' ? SNDRV_PCM_STREAM_CAPTURE : SNDRV_PCM_STREAM_PLAYBACK;
        event("open-pcm", stream);
        if (failure("open-pcm", EBUSY)) return -1;
        if (card != (baseline ? 0 : 7)) abort();
        return 1000;
    }
    abort();
}
int __wrap_fstat(int fd, struct stat *st)
{
    event(fd == 1000 ? "stat-pcm" : "stat-control", fd);
    if (failure(fd == 1000 ? "stat-pcm" : "stat-control", EIO)) return -1;
    memset(st, 0, sizeof(*st)); st->st_mode = S_IFCHR | 0600; st->st_rdev = makedev(116, 99);
    if (is_case("wrong-major")) st->st_rdev = makedev(1, 3);
    return 0;
}
int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list ap; void *arg = NULL;
    if (request != SNDRV_PCM_IOCTL_PREPARE && request != SNDRV_PCM_IOCTL_START && request != SNDRV_PCM_IOCTL_DROP && request != SNDRV_PCM_IOCTL_HW_FREE) {
        va_start(ap, request); arg = va_arg(ap, void *); va_end(ap);
    }
    if (request == SNDRV_CTL_IOCTL_CARD_INFO) {
        event("card-info", fd-100);
        if (failure("card-info", EIO)) return -1;
        struct snd_ctl_card_info *info = arg;
        memset(info, 0, sizeof(*info)); info->card = fd-100;
        strcpy((char *)info->id, is_case("wrong-card") || (is_case("other-control") && fd == 100) ? "othercard" : "rockchiprk809co");
        strcpy((char *)info->driver, "rockchip_rk809-");
        strcpy((char *)info->name, "rockchip,rk809-codec");
        strcpy((char *)info->longname, "rockchip,rk809-codec");
        if (is_case("wrong-driver")) strcpy((char *)info->driver, "unknown");
        if (is_case("wrong-name")) strcpy((char *)info->name, "unknown");
        if (is_case("wrong-longname")) strcpy((char *)info->longname, "unknown");
        if (is_case("card-unterminated")) memset(info->id, 'a', sizeof(info->id));
        return 0;
    }
    if (fd != 1000) abort();
    if (request == SNDRV_PCM_IOCTL_PVERSION) {
        event("version", 0); if (failure("version", EIO)) return -1;
        *(int *)arg = is_case("wrong-version") ? -1 : SNDRV_PCM_VERSION; return 0;
    }
    if (request == SNDRV_PCM_IOCTL_INFO) {
        event("info", stream); if (failure("info", EIO)) return -1;
        struct snd_pcm_info *info = arg;
        memset(info, 0, sizeof(*info)); info->card = baseline ? 0 : 7;
        info->stream = stream; info->subdevices_count = info->subdevices_avail = 1;
        strcpy((char *)info->id, "fe410000.i2s-rk817-hifi rk817-hifi-0");
        strcpy((char *)info->name, (char *)info->id);
        if (is_case("wrong-pcm")) strcpy((char *)info->name, "unrelated");
        return 0;
    }
    if (request == SNDRV_PCM_IOCTL_HW_REFINE) {
        event("refine", 0); if (failure("refine", EIO)) return -1; return 0;
    }
    if (request == SNDRV_PCM_IOCTL_HW_PARAMS) {
        event("params", 0); if (failure("params", EREMOTEIO)) return -1;
        state = SNDRV_PCM_STATE_SETUP;
        struct snd_pcm_hw_params *p = arg;
        if (is_case("params-mismatch")) p->intervals[SNDRV_PCM_HW_PARAM_RATE-SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].max = 44100;
        return 0;
    }
    if (request == SNDRV_PCM_IOCTL_SW_PARAMS) {
        event("sw-params", 0); if (failure("sw-params", EIO)) return -1;
        struct snd_pcm_sw_params *p = arg;
        if (p->start_threshold <= 1024 || p->avail_min != 256 || p->stop_threshold != 1024 || p->silence_size != 0) abort();
        p->boundary = 1UL << 62;
        if (is_case("sw-mismatch")) p->start_threshold = 1;
        return 0;
    }
    if (request == SNDRV_PCM_IOCTL_PREPARE) {
        event("prepare", 0); if (failure("prepare", EIO) || failure("prepare-eintr", EINTR)) return -1;
        if (state != SNDRV_PCM_STATE_SETUP) abort();
        state = SNDRV_PCM_STATE_PREPARED; return 0;
    }
    if (request == SNDRV_PCM_IOCTL_START) {
        event("start", ++start_calls); if (failure("start", EREMOTEIO) || failure("start-eintr", EINTR)) return -1;
        if (state != SNDRV_PCM_STATE_PREPARED || start_calls != 1 || (stream == 0 && queued != 1024)) abort();
        state = SNDRV_PCM_STATE_RUNNING; return 0;
    }
    if (request == SNDRV_PCM_IOCTL_STATUS) {
        event("status", state); if (failure("status", EIO)) return -1;
        struct snd_pcm_status *s = arg; memset(s, 0, sizeof(*s)); s->state = state;
        s->appl_ptr = stream == 0 ? queued : received;
        s->hw_ptr = state == SNDRV_PCM_STATE_RUNNING && polls ? 512 : 0;
        if (is_case("no-hardware-progress")) s->hw_ptr = 0;
        if (is_case("state-xrun") && state == SNDRV_PCM_STATE_RUNNING) s->state = SNDRV_PCM_STATE_XRUN;
        if (is_case("bad-prepared") && state == SNDRV_PCM_STATE_PREPARED) s->state = SNDRV_PCM_STATE_SETUP;
        return 0;
    }
    if (request == SNDRV_PCM_IOCTL_DROP) {
        event("drop", ++drop_calls); if (failure("drop", EIO) || failure("drop-eintr", EINTR) || failure("xrun-cleanup-errors", EIO)) return -1;
        if (state == SNDRV_PCM_STATE_OPEN) { errno = EBADFD; return -1; }
        state = SNDRV_PCM_STATE_SETUP; return 0;
    }
    if (request == SNDRV_PCM_IOCTL_HW_FREE) {
        event("free", ++free_calls); if (failure("free", EIO) || failure("free-eintr", EINTR) || failure("xrun-cleanup-errors", EIO)) return -1;
        if (state != SNDRV_PCM_STATE_SETUP && state != SNDRV_PCM_STATE_PREPARED) { errno = EBADFD; return -1; }
        state = SNDRV_PCM_STATE_OPEN; return 0;
    }
    abort();
}
int __real_poll(struct pollfd *, nfds_t, int);
int __wrap_poll(struct pollfd *fds, nfds_t count, int timeout)
{
    event("poll", timeout); polls++;
    if (count != 1 || fds[0].fd != 1000 || timeout <= 0 || timeout > 100) abort();
    if (is_case("real-timer")) return __real_poll(NULL, 0, 1000);
    if (is_case("poll-eintr") && !event_fired) { event_fired = true; errno = EINTR; return -1; }
    if (is_case("log-capacity")) { errno = EINTR; return -1; }
    if (is_case("signal-stop") && !event_fired) { event_fired = true; raise(SIGTERM); errno = EINTR; return -1; }
    if (is_case("poll-error")) { errno = EIO; return -1; }
    if (is_case("poll-timeout")) { milliseconds += timeout; fds[0].revents = 0; return 0; }
    if (is_case("poll-hangup")) { fds[0].revents = POLLHUP; return 1; }
    if (is_case("poll-xrun")) { fds[0].revents = POLLERR; return 1; }
    fds[0].revents = fds[0].events; return 1;
}
int __wrap___poll_chk(struct pollfd *fds, nfds_t count, int timeout, size_t size)
{ if (size < count * sizeof(*fds)) abort(); return __wrap_poll(fds, count, timeout); }
static ssize_t transfer(void *buffer, size_t count, bool capture)
{
    event(capture ? "read" : "write", count);
    if (!count || count > 1024 || count % 4 || capture != (stream == 1)) abort();
    if (capture && state != SNDRV_PCM_STATE_RUNNING) abort();
    if (!capture && state != SNDRV_PCM_STATE_PREPARED && state != SNDRV_PCM_STATE_RUNNING) abort();
    unsigned int call = capture ? ++reads : ++writes;
    if ((is_case("io-eintr") || is_case("io-eagain")) && call == 1) { errno = is_case("io-eintr") ? EINTR : EAGAIN; return -1; }
    if (is_case("io-always-eagain")) { milliseconds += 50; errno = EAGAIN; return -1; }
    if (is_case("signal-io") && !event_fired) { event_fired = true; raise(SIGINT); errno = EINTR; return -1; }
    if ((is_case("xrun") || is_case("xrun-cleanup-errors")) && state == SNDRV_PCM_STATE_RUNNING) { state = SNDRV_PCM_STATE_XRUN; errno = EPIPE; return -1; }
    if (is_case("io-error")) { errno = EIO; return -1; }
    if (is_case("io-zero")) return 0;
    if (is_case("io-misaligned")) return 1;
    if (is_case("io-oversize")) return count + 4;
    if (is_case("short-io") && count > 4) count /= 2;
    if (capture) {
        int16_t *samples = buffer;
        for (size_t i = 0; i < count / 2; i++) samples[i] = i % 2 ? 1 : 0;
        received += count / 4;
    } else {
        unsigned char *bytes = buffer;
        for (size_t i = 0; i < count; i++) if (bytes[i]) abort();
        queued += count / 4;
    }
    return count;
}
ssize_t __wrap_read(int fd, void *buffer, size_t count)
{ if (fd != 1000) abort(); return transfer(buffer, count, true); }
ssize_t __wrap___read_chk(int fd, void *buffer, size_t count, size_t size)
{ if (count > size) abort(); return __wrap_read(fd, buffer, count); }
ssize_t __wrap_write(int fd, const void *buffer, size_t count)
{ if (fd != 1000) abort(); return transfer((void *)buffer, count, false); }
int __wrap_close(int fd)
{
    event(fd == 1000 ? "close-pcm" : "close-control", fd);
    if (fd == 1000) { closes++; if (closes > 1) abort(); if (failure("close-pcm", EIO) || failure("close-eintr", EINTR) || failure("xrun-cleanup-errors", EIO)) return -1; }
    else if (failure("close-control", EIO)) return -1;
    return 0;
}
int __real_clock_gettime(clockid_t, struct timespec *);
int __wrap_clock_gettime(clockid_t clock, struct timespec *time)
{
    if (is_case("real-timer")) return __real_clock_gettime(clock, time);
    if (failure("clock", EIO)) return -1;
    if (!is_case("log-capacity")) milliseconds++;
    time->tv_sec = milliseconds / 1000; time->tv_nsec = (milliseconds % 1000) * 1000000L;
    return 0;
}
int __real_setitimer(int, const struct itimerval *, struct itimerval *);
int __wrap_setitimer(int which, const struct itimerval *value, struct itimerval *old)
{
    event(value->it_value.tv_sec || value->it_value.tv_usec ? "timer-on" : "timer-off", which);
    timer_armed = value->it_value.tv_sec || value->it_value.tv_usec;
    if (failure("timer", EIO)) return -1;
    if (is_case("real-timer")) return __real_setitimer(which, value, old);
    return 0;
}
size_t __real_fwrite(const void *, size_t, size_t, FILE *);
size_t __wrap_fwrite(const void *data, size_t size, size_t count, FILE *file)
{
    if (is_case("output-deadline") && timer_armed && closes && !event_fired) {
        event_fired = true;
        raise(SIGALRM);
    }
    return __real_fwrite(data, size, count, file);
}
