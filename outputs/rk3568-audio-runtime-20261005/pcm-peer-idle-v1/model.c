/* SPDX-License-Identifier: MIT */
/* External libc boundaries only: the source-under-test's real main executes. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include ALSA_LOCKED_UAPI

int peer_main(int, char **);
int __real_sigemptyset(sigset_t *);
int __real_sigaddset(sigset_t *, int);
int __real_sigaction(int, const struct sigaction *, struct sigaction *);
int __real_sigprocmask(int, const sigset_t *, sigset_t *);
unsigned int __real_alarm(unsigned int);

struct resource {
    int fd, opened, closed, stat_calls, version_calls, info_calls;
    int refines, params_calls, configured, setup_calls, peer_calls;
    int free_calls, open_state_calls, close_calls, freed_ok;
};
static struct resource pcm[2];
static int card, open_first, close_first, ctl_opened, ctl_closed, ctl_stat, ctl_info, ctl_close;
static int violations, failed, first_errno, empty_calls, action_calls, add_calls, unblock_calls, armed;
static unsigned int events;
static char trace[4096], first_event[64];
static const char *faults, *bad, *deadline;
static const char identity[] = "fe410000.i2s-rk817-hifi rk817-hifi-0";

static void event(const char *name)
{
    size_t used = strlen(trace), length = strlen(name);
    if (used + length + 2 >= sizeof(trace)) { violations++; return; }
    snprintf(trace + used, sizeof(trace) - used, "%s%s", used ? "," : "", name);
    events++;
}

static void failure(const char *name, int error)
{
    if (!failed) {
        snprintf(first_event, sizeof(first_event), "%s", name);
        first_errno = error;
    }
    failed = 1;
}

static int injection(const char *name)
{
    char key[80];
    snprintf(key, sizeof(key), "%s:", name);
    const char *item = faults;
    while (item && *item) {
        if (!strncmp(item, key, strlen(key))) {
            int value = atoi(item + strlen(key));
            failure(name, value < 0 ? -value : EPROTO);
            errno = value < 0 ? -value : 0;
            return value < 0 ? -1 : value;
        }
        item = strchr(item, ',');
        if (item) item++;
    }
    return 0;
}

static const char *bad_at(const char *name)
{
    if (!bad || strncmp(bad, name, strlen(name)) || bad[strlen(name)] != ':') return NULL;
    failure(name, EPROTO);
    return bad + strlen(name) + 1;
}

static int is(const char *value, const char *wanted)
{
    return value && !strcmp(value, wanted);
}

static void normal_only(void) { violations += failed; }

int __wrap_sigemptyset(sigset_t *set)
{
    normal_only();
    const char *name = empty_calls++ ? "empty-unblock" : "empty-action";
    event(name);
    violations += empty_calls > 2;
    int result = injection(name);
    return result ? result : __real_sigemptyset(set);
}

int __wrap_sigaction(int sig, const struct sigaction *action, struct sigaction *old)
{
    normal_only(); event("action");
    violations += ++action_calls != 1 || empty_calls != 1 || sig != SIGALRM || !action ||
        action->sa_handler != SIG_DFL || action->sa_flags || old != NULL;
    int result = injection("action");
    return result ? result : __real_sigaction(sig, action, old);
}

int __wrap_sigaddset(sigset_t *set, int sig)
{
    normal_only(); event("add");
    violations += ++add_calls != 1 || sig != SIGALRM || empty_calls != 2;
    int result = injection("add");
    return result ? result : __real_sigaddset(set, sig);
}

int __wrap_sigprocmask(int how, const sigset_t *set, sigset_t *old)
{
    normal_only(); event("unblock");
    violations += ++unblock_calls != 1 || how != SIG_UNBLOCK || !set ||
        sigismember(set, SIGALRM) != 1 || old != NULL || action_calls != 1 || add_calls != 1;
    int result = injection("unblock");
    return result ? result : __real_sigprocmask(how, set, old);
}

unsigned int __wrap_alarm(unsigned int seconds)
{
    event(seconds == 5 ? "alarm5" : "alarm0");
    violations += seconds != 0 && seconds != 5;
    if (seconds == 5) {
        normal_only(); violations += armed || unblock_calls != 1; armed = 1;
    } else {
        violations += !armed || (ctl_opened && !ctl_closed);
        for (int s = 0; s < 2; s++) violations += pcm[s].opened && !pcm[s].closed;
        armed = 0;
    }
    return __real_alarm(seconds);
}

int __wrap_open(const char *path, int flags, ...)
{
    normal_only();
    violations += !armed || flags != (O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    char wanted[64];
    snprintf(wanted, sizeof(wanted), "/dev/snd/controlC%d", card);
    if (!strcmp(path, wanted)) {
        event("ctl-open"); violations += ctl_opened || ctl_closed;
        int result = injection("ctl-open");
        if (result) return -1;
        ctl_opened = 1; return 60;
    }
    for (int s = 0; s < 2; s++) {
        snprintf(wanted, sizeof(wanted), "/dev/snd/pcmC%dD0%c", card, s ? 'c' : 'p');
        if (!strcmp(path, wanted)) {
            char name[16]; snprintf(name, sizeof(name), "%c-open", s ? 'c' : 'p'); event(name);
            violations += !ctl_closed || pcm[s].opened;
            if (!pcm[!s].opened) violations += s != open_first;
            else violations += pcm[!s].setup_calls != 1 || pcm[!s].closed;
            int result = injection(name);
            if (result) return -1;
            pcm[s].opened = 1; pcm[s].fd = 61 + s; return pcm[s].fd;
        }
    }
    event("FORBIDDEN_OPEN"); violations++; errno = EPERM; return -1;
}

static struct resource *resource(int fd, int *stream)
{
    for (int s = 0; s < 2; s++) if (pcm[s].opened && pcm[s].fd == fd && !pcm[s].closed) {
        *stream = s; return &pcm[s];
    }
    violations++; *stream = 0; return &pcm[0];
}

int __wrap_fstat(int fd, struct stat *st)
{
    normal_only();
    char name[16];
    if (fd == 60) { strcpy(name, "ctl-stat"); violations += !ctl_opened || ctl_closed || ++ctl_stat != 1; }
    else { int s; struct resource *r = resource(fd, &s); snprintf(name, sizeof(name), "%c-stat", s ? 'c' : 'p'); violations += ++r->stat_calls != 1; }
    event(name);
    int result = injection(name);
    if (result) return result;
    memset(st, 0, sizeof(*st)); st->st_mode = S_IFCHR | 0600; st->st_rdev = makedev(116, 197 + fd);
    const char *b = bad_at(name);
    if (is(b, "regular")) st->st_mode = S_IFREG | 0600;
    if (is(b, "major")) st->st_rdev = makedev(1, 3);
    return 0;
}

static void check_params(const struct snd_pcm_hw_params *p, int exact)
{
    violations += p->flags != 0 || p->rmask != ~0U || p->cmask != 0 || p->info != 0;
    for (int m = 0; m < 3; m++) for (int n = 0; n < 8; n++) {
        unsigned int mask = exact ? (n == 0 ? (1U << (m == 0 ? 3 : m == 1 ? 2 : 0)) : 0) : UINT_MAX;
        violations += p->masks[m].bits[n] != mask;
    }
    static const int indices[] = {0, 1, 2, 3, 5, 6, 7, 9, 10};
    static const unsigned int values[] = {16, 32, 2, 48000, 256, 1024, 4, 1024, 4096};
    for (int n = 0; n < 12; n++) if (!exact) violations += p->intervals[n].min != 0 || p->intervals[n].max != UINT_MAX;
    for (int n = 0; n < 9; n++) if (exact) {
        const struct snd_interval *i = &p->intervals[indices[n]];
        violations += i->min != values[n] || i->max != values[n] || i->empty || i->openmin || i->openmax || !i->integer;
    }
}

static void alter_params(struct snd_pcm_hw_params *p, const char *b)
{
    if (!b) return;
    if (!strncmp(b, "interval", 8)) {
        int n = atoi(b + 8); if (n >= 0 && n < 12) p->intervals[n].min = p->intervals[n].max = 1;
    }
    if (!strncmp(b, "mask", 4)) { int n = atoi(b + 4); if (n >= 0 && n < 3) p->masks[n].bits[0] ^= 2; }
    if (!strncmp(b, "extra", 5)) { int n = atoi(b + 5); if (n >= 0 && n < 3) p->masks[n].bits[7] = 1; }
    if (is(b, "openmin")) p->intervals[3].openmin = 1;
    if (is(b, "openmax")) p->intervals[3].openmax = 1;
    if (is(b, "empty")) p->intervals[3].empty = 1;
    if (is(b, "wide")) p->intervals[3].max++;
}

int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list ap; va_start(ap, request);
    void *arg = request == SNDRV_PCM_IOCTL_HW_FREE ? NULL : va_arg(ap, void *);
    va_end(ap);
    if (fd == 60 && request == SNDRV_CTL_IOCTL_CARD_INFO) {
        normal_only(); event("card-info"); violations += !ctl_stat || ++ctl_info != 1;
        int result = injection("card-info"); if (result) return result;
        struct snd_ctl_card_info *i = arg; memset(i, 0, sizeof(*i)); i->card = card;
        memcpy(i->id, "rockchiprk809co\0", sizeof(i->id));
        const char *b = bad_at("card-info");
        if (is(b, "card")) i->card++;
        if (is(b, "usb")) strcpy((char *)i->id, "USB-Audio");
        if (is(b, "unterminated")) memset(i->id, 'x', sizeof(i->id));
        if (is(b, "tail")) i->id[15] = 'x';
        return 0;
    }
    int s; struct resource *r = resource(fd, &s);
    char name[32]; const char *operation = NULL;
    if (request == SNDRV_PCM_IOCTL_PVERSION) { normal_only(); operation = "version"; violations += !r->stat_calls || ++r->version_calls != 1; }
    else if (request == SNDRV_PCM_IOCTL_INFO) { normal_only(); operation = "info"; violations += !r->version_calls || ++r->info_calls != 1; }
    else if (request == SNDRV_PCM_IOCTL_HW_REFINE) { normal_only(); operation = ++r->refines == 1 ? "full" : "exact"; violations += !r->info_calls || r->refines > 2; check_params(arg, r->refines == 2); }
    else if (request == SNDRV_PCM_IOCTL_HW_PARAMS) { normal_only(); operation = "params"; violations += r->refines != 2 || ++r->params_calls != 1; check_params(arg, 1); }
    else if (request == SNDRV_PCM_IOCTL_HW_FREE) {
        operation = "free"; violations += !r->configured || ++r->free_calls != 1;
        if (!failed) {
            violations += !pcm[0].setup_calls || !pcm[1].setup_calls;
            if (!pcm[!s].closed) violations += s != close_first;
            else violations += r->peer_calls != 1;
        }
        r->configured = 0;
    } else if (request == SNDRV_PCM_IOCTL_STATUS) {
        normal_only();
        if (r->free_calls) { operation = "open-state"; violations += !r->freed_ok || ++r->open_state_calls != 1; }
        else if (!r->setup_calls) { operation = "setup"; violations += !r->configured; r->setup_calls++; }
        else { operation = "peer-setup"; violations += !r->configured || ++r->peer_calls != 1 || !pcm[!s].closed || s == close_first; }
    } else { event("FORBIDDEN_IOCTL"); violations++; errno = EPERM; return -1; }
    snprintf(name, sizeof(name), "%c-%s", s ? 'c' : 'p', operation); event(name);
    if (deadline && !strcmp(deadline, name)) for (;;) pause();
    int result = injection(name);
    if (result < 0) return result;
    const char *b = result ? NULL : bad_at(name);
    if (request == SNDRV_PCM_IOCTL_PVERSION) { *(int *)arg = SNDRV_PCM_VERSION; if (b) *(int *)arg = -1; }
    else if (request == SNDRV_PCM_IOCTL_INFO) {
        struct snd_pcm_info *i = arg; memset(i, 0, sizeof(*i)); i->card = card; i->stream = s;
        memcpy(i->id, identity, sizeof(identity)); memcpy(i->name, identity, sizeof(identity));
        strcpy((char *)i->subname, "subdevice #0"); i->subdevices_count = 1;
        if (is(b, "card")) i->card++;
        if (is(b, "device")) i->device++;
        if (is(b, "subdevice")) i->subdevice++;
        if (is(b, "stream")) i->stream = !s;
        if (is(b, "id")) i->id[0] = 'x';
        if (is(b, "name")) i->name[0] = 'x';
        if (is(b, "short")) strcpy((char *)i->id, "fe410000.i2s-rk817-hifi");
        if (is(b, "id-unterm")) memset(i->id, 'x', sizeof(i->id));
        if (is(b, "name-unterm")) memset(i->name, 'x', sizeof(i->name));
        if (is(b, "subname-unterm")) memset(i->subname, 'x', sizeof(i->subname));
        if (is(b, "control")) i->id[3] = '\n';
        if (is(b, "count")) i->subdevices_count = 2;
        if (is(b, "avail")) i->subdevices_avail = 2;
    } else if (request == SNDRV_PCM_IOCTL_HW_REFINE) {
        struct snd_pcm_hw_params *p = arg;
        if (r->refines == 1) {
            memset(p, 0, sizeof(*p));
            for (int m = 0; m < 3; m++) for (int n = 0; n < 8; n++) p->masks[m].bits[n] = UINT_MAX;
            for (int n = 0; n < 12; n++) p->intervals[n].max = UINT_MAX;
            if (is(b, "mask-empty")) memset(&p->masks[0], 0, sizeof(p->masks[0]));
            if (is(b, "interval-empty")) p->intervals[3].empty = 1;
            if (is(b, "inverted")) { p->intervals[3].min = 1; p->intervals[3].max = 0; }
            if (is(b, "open-singleton")) { p->intervals[3].min = p->intervals[3].max = 48000; p->intervals[3].openmin = 1; }
            if (is(b, "no-rate")) p->intervals[3].max = 44100;
            if (is(b, "no-mask")) p->masks[0].bits[0] &= ~(1U << 3);
        } else alter_params(p, b);
        p->rmask = 0; p->cmask = 0; p->info = SNDRV_PCM_INFO_INTERLEAVED;
    } else if (request == SNDRV_PCM_IOCTL_HW_PARAMS) { r->configured = 1; alter_params(arg, b); }
    else if (request == SNDRV_PCM_IOCTL_HW_FREE) r->freed_ok = result == 0;
    else if (request == SNDRV_PCM_IOCTL_STATUS) {
        struct snd_pcm_status *i = arg; memset(i, 0, sizeof(*i)); i->state = r->free_calls ? SNDRV_PCM_STATE_OPEN : SNDRV_PCM_STATE_SETUP;
        if (is(b, "running")) i->state = SNDRV_PCM_STATE_RUNNING;
        if (is(b, "prepared")) i->state = SNDRV_PCM_STATE_PREPARED;
        if (is(b, "wrong")) i->state = r->free_calls ? SNDRV_PCM_STATE_SETUP : SNDRV_PCM_STATE_OPEN;
        if (is(b, "appl")) i->appl_ptr = 1;
        if (is(b, "hw")) i->hw_ptr = 1;
    }
    return result;
}

int __wrap_close(int fd)
{
    char name[16];
    if (fd == 60) {
        strcpy(name, "ctl-close"); violations += !ctl_opened || ctl_closed || ++ctl_close != 1;
        if (!failed) violations += ctl_stat != 1 || ctl_info != 1;
        ctl_closed = 1;
    } else {
        int s; struct resource *r = resource(fd, &s); snprintf(name, sizeof(name), "%c-close", s ? 'c' : 'p');
        violations += ++r->close_calls != 1 || (r->configured && !r->free_calls);
        r->closed = 1;
    }
    event(name); return injection(name);
}

/* Any accidental alternate device/data path is observable, never delegated. */
int __wrap_openat(int fd, const char *path, int flags, ...) { (void)fd; (void)path; (void)flags; event("FORBIDDEN_OPENAT"); violations++; errno = EPERM; return -1; }
ssize_t __wrap_read(int fd, void *p, size_t n) { (void)fd; (void)p; (void)n; event("FORBIDDEN_READ"); violations++; errno = EPERM; return -1; }
ssize_t __wrap_write(int fd, const void *p, size_t n) { (void)fd; (void)p; (void)n; event("FORBIDDEN_WRITE"); violations++; errno = EPERM; return -1; }
long __wrap_syscall(long n, ...) { (void)n; event("FORBIDDEN_SYSCALL"); violations++; errno = EPERM; return -1; }
int __wrap_fcntl(int fd, int cmd, ...) { (void)fd; (void)cmd; event("FORBIDDEN_FCNTL"); violations++; errno = EPERM; return -1; }
int __wrap_system(const char *cmd) { (void)cmd; event("FORBIDDEN_SYSTEM"); violations++; errno = EPERM; return -1; }

int main(int argc, char **argv)
{
    faults = getenv("PEER_FAULTS"); bad = getenv("PEER_BAD"); deadline = getenv("PEER_DEADLINE");
    card = argc > 2 ? atoi(argv[2]) : 0;
    open_first = argc > 4 && !strcmp(argv[4], "capture"); close_first = argc > 6 && !strcmp(argv[6], "capture");
    if (deadline) {
        struct sigaction a; memset(&a, 0, sizeof(a)); a.sa_handler = SIG_IGN;
        sigset_t blocked; __real_sigemptyset(&blocked); __real_sigaddset(&blocked, SIGALRM);
        if (__real_sigaction(SIGALRM, &a, NULL) || __real_sigprocmask(SIG_BLOCK, &blocked, NULL)) return 99;
    }
    int result = peer_main(argc, argv);
    if (!getenv("PEER_INVALID")) {
        if (!failed) {
            violations += result != 0 || ctl_close != 1;
            for (int s = 0; s < 2; s++) violations += pcm[s].params_calls != 1 || pcm[s].setup_calls != 1 ||
                pcm[s].free_calls != 1 || pcm[s].open_state_calls != 1 || pcm[s].close_calls != 1 || pcm[s].peer_calls != (s != close_first);
        } else violations += result != 2;
    } else violations += events != 0 || result != 2;
    violations += (ctl_opened && !ctl_closed) || armed;
    for (int s = 0; s < 2; s++) violations += pcm[s].opened && !pcm[s].closed;
    fprintf(stderr, "PEER_MODEL {\"rc\":%d,\"violations\":%d,\"events\":%u,\"trace\":\"%s\",\"first_event\":\"%s\",\"first_errno\":%d,\"free\":[%d,%d],\"close\":[%d,%d]}\n",
            result, violations, events, trace, first_event, first_errno, pcm[0].free_calls, pcm[1].free_calls, pcm[0].close_calls, pcm[1].close_calls);
    return result;
}
