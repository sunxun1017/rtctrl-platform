/* SPDX-License-Identifier: MIT */
/* Two fixed-identity PCM configurations, peer-idle observation, no START or I/O. */
#include "parameters.h"

#define MAX_RECORDS 64
struct operation {
    char name[32];
    long long rc;
    int error, state;
    unsigned long long appl_ptr, hw_ptr;
};
struct context {
    struct operation records[MAX_RECORDS];
    unsigned int count, first_sequence;
    int first_error;
    char first_name[32];
};
struct pcm {
    int fd, stream, configured;
};

static void fail(struct context *ctx, const char *name, int error)
{
    if (!ctx->first_error) {
        ctx->first_error = error ? error : EPROTO;
        ctx->first_sequence = ctx->count;
        snprintf(ctx->first_name, sizeof(ctx->first_name), "%s", name);
    }
}

static int observed(struct context *ctx, const char *name, long long rc, int okay)
{
    const int error = rc < 0 ? errno : 0;
    if (ctx->count == MAX_RECORDS) {
        fail(ctx, "record-capacity", ENOSPC);
        return 0;
    }
    struct operation *record = &ctx->records[ctx->count++];
    snprintf(record->name, sizeof(record->name), "%s", name);
    record->rc = rc;
    record->error = error;
    record->state = -1;
    if (!okay) fail(ctx, name, error);
    return okay;
}

static const char *name_of(int stream, unsigned int operation)
{
    static const char *const names[2][11] = {
        {"p-open", "p-stat", "p-version", "p-info", "p-full", "p-exact", "p-params", "p-setup", "p-free", "p-open-state", "p-close"},
        {"c-open", "c-stat", "c-version", "c-info", "c-full", "c-exact", "c-params", "c-setup", "c-free", "c-open-state", "c-close"}
    };
    return names[stream][operation];
}

static int request(struct context *ctx, struct pcm *pcm, const char *name,
                   unsigned long command, void *arg)
{
    errno = 0;
    int rc = ioctl(pcm->fd, command, arg);
    observed(ctx, name, rc, rc == 0);
    return rc;
}

static int state(struct context *ctx, struct pcm *pcm, const char *name, int wanted)
{
    struct snd_pcm_status status;
    memset(&status, 0, sizeof(status));
    if (request(ctx, pcm, name, SNDRV_PCM_IOCTL_STATUS, &status) != 0) return 0;
    struct operation *record = &ctx->records[ctx->count - 1];
    record->state = status.state;
    record->appl_ptr = status.appl_ptr;
    record->hw_ptr = status.hw_ptr;
    if (status.state != wanted ||
        (wanted == SNDRV_PCM_STATE_SETUP && (status.appl_ptr != 0 || status.hw_ptr != 0))) {
        fail(ctx, name, EPROTO);
        return 0;
    }
    return 1;
}

static int configure(struct context *ctx, struct pcm *pcm, int card)
{
    char path[64];
    const int s = pcm->stream;
    snprintf(path, sizeof(path), "/dev/snd/pcmC%dD0%c", card, s ? 'c' : 'p');
    errno = 0;
    pcm->fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    if (!observed(ctx, name_of(s, 0), pcm->fd, pcm->fd >= 0)) return 0;
    struct stat st;
    errno = 0;
    int stat_rc = fstat(pcm->fd, &st);
    if (!observed(ctx, name_of(s, 1), stat_rc, stat_rc == 0)) return 0;
    if (!S_ISCHR(st.st_mode) || major(st.st_rdev) != 116) {
        fail(ctx, name_of(s, 1), EPROTO);
        return 0;
    }
    int version = -1;
    if (request(ctx, pcm, name_of(s, 2), SNDRV_PCM_IOCTL_PVERSION, &version) != 0) return 0;
    if (version != SNDRV_PCM_VERSION) { fail(ctx, name_of(s, 2), EPROTO); return 0; }
    struct snd_pcm_info info;
    memset(&info, 0xff, sizeof(info));
    if (request(ctx, pcm, name_of(s, 3), SNDRV_PCM_IOCTL_INFO, &info) != 0) return 0;
    if (!pcm_info_valid(&info, card, s)) { fail(ctx, name_of(s, 3), EPROTO); return 0; }
    struct snd_pcm_hw_params params;
    params_any(&params);
    if (request(ctx, pcm, name_of(s, 4), SNDRV_PCM_IOCTL_HW_REFINE, &params) != 0) return 0;
    if (!caps_valid(&params) || !caps_allow_exact(&params)) { fail(ctx, name_of(s, 4), EPROTO); return 0; }
    params_exact(&params);
    if (request(ctx, pcm, name_of(s, 5), SNDRV_PCM_IOCTL_HW_REFINE, &params) != 0) return 0;
    if (!exact_valid(&params)) { fail(ctx, name_of(s, 5), EPROTO); return 0; }
    params_exact(&params);
    int rc = request(ctx, pcm, name_of(s, 6), SNDRV_PCM_IOCTL_HW_PARAMS, &params);
    /* A nonnegative return acquired configuration, even if an abnormal positive
     * result or invalid returned parameters must subsequently be rejected. */
    pcm->configured = rc >= 0;
    if (rc != 0) return 0;
    if (!exact_valid(&params)) { fail(ctx, name_of(s, 6), EPROTO); return 0; }
    return state(ctx, pcm, name_of(s, 7), SNDRV_PCM_STATE_SETUP);
}

static void release(struct context *ctx, struct pcm *pcm, int check_open)
{
    if (pcm->fd < 0) return;
    const int s = pcm->stream;
    if (pcm->configured) {
        pcm->configured = 0;
        if (request(ctx, pcm, name_of(s, 8), SNDRV_PCM_IOCTL_HW_FREE, NULL) == 0 && check_open)
            state(ctx, pcm, name_of(s, 9), SNDRV_PCM_STATE_OPEN);
    }
    const int fd = pcm->fd;
    pcm->fd = -1; /* close/EINTR is never retried. */
    errno = 0;
    int rc = close(fd);
    observed(ctx, name_of(s, 10), rc, rc == 0);
}

static void output(const struct context *ctx)
{
    for (unsigned int i = 0; i < ctx->count; i++) {
        const struct operation *record = &ctx->records[i];
        printf("PCM_PEER_OP seq=%u name=%s rc=%lld errno=%d state=%d appl_ptr=%llu hw_ptr=%llu\n",
               i + 1, record->name, record->rc, record->error, record->state,
               record->appl_ptr, record->hw_ptr);
    }
    if (ctx->first_error)
        fprintf(stderr, "PCM_PEER_FAILED seq=%u name=%s errno=%d\n",
                ctx->first_sequence, ctx->first_name, ctx->first_error);
    else
        puts("PCM_PEER_IDLE_VERIFIED_NO_START");
}

int main(int argc, char **argv)
{
    if (argc != 7 || strcmp(argv[1], "--card") || strlen(argv[2]) != 1 || argv[2][0] < '0' || argv[2][0] > '7' ||
        strcmp(argv[3], "--open-first") || (strcmp(argv[4], "playback") && strcmp(argv[4], "capture")) ||
        strcmp(argv[5], "--close-first") || (strcmp(argv[6], "playback") && strcmp(argv[6], "capture"))) {
        fprintf(stderr, "usage: pcm-peer-idle --card N --open-first playback|capture --close-first playback|capture (N=0..7)\n");
        return 2;
    }
    const int card = argv[2][0] - '0';
    const int open_first = !strcmp(argv[4], "capture"), close_first = !strcmp(argv[6], "capture");
    struct context ctx;
    memset(&ctx, 0, sizeof(ctx));
    struct pcm pcm[2] = {{-1, SNDRV_PCM_STREAM_PLAYBACK, 0}, {-1, SNDRV_PCM_STREAM_CAPTURE, 0}};
    int control = -1, armed = 0;
    struct sigaction action;
    sigset_t unblock;
    memset(&action, 0, sizeof(action));
    action.sa_handler = SIG_DFL;
    errno = 0;
    int rc = sigemptyset(&action.sa_mask);
    if (!observed(&ctx, "empty-action", rc, rc == 0)) goto cleanup;
    errno = 0;
    rc = sigaction(SIGALRM, &action, NULL);
    if (!observed(&ctx, "action", rc, rc == 0)) goto cleanup;
    errno = 0;
    rc = sigemptyset(&unblock);
    if (!observed(&ctx, "empty-unblock", rc, rc == 0)) goto cleanup;
    errno = 0;
    rc = sigaddset(&unblock, SIGALRM);
    if (!observed(&ctx, "add", rc, rc == 0)) goto cleanup;
    errno = 0;
    rc = sigprocmask(SIG_UNBLOCK, &unblock, NULL);
    if (!observed(&ctx, "unblock", rc, rc == 0)) goto cleanup;
    /* Clear inherited ignore/block before a five-second default signal deadline.
     * An uninterruptible kernel wait may defer delivery past this deadline. */
    errno = 0;
    observed(&ctx, "alarm5", alarm(5), 1);
    armed = 1;
    char path[64];
    snprintf(path, sizeof(path), "/dev/snd/controlC%d", card);
    errno = 0;
    control = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    if (!observed(&ctx, "ctl-open", control, control >= 0)) goto cleanup;
    struct stat st;
    errno = 0;
    rc = fstat(control, &st);
    if (!observed(&ctx, "ctl-stat", rc, rc == 0)) goto cleanup;
    if (!S_ISCHR(st.st_mode) || major(st.st_rdev) != 116) { fail(&ctx, "ctl-stat", EPROTO); goto cleanup; }
    struct snd_ctl_card_info info;
    memset(&info, 0xff, sizeof(info));
    errno = 0;
    rc = ioctl(control, SNDRV_CTL_IOCTL_CARD_INFO, &info);
    if (!observed(&ctx, "card-info", rc, rc == 0)) goto cleanup;
    if (info.card != card || memcmp(info.id, "rockchiprk809co\0", sizeof(info.id))) { fail(&ctx, "card-info", EPROTO); goto cleanup; }
    const int fd = control;
    control = -1;
    errno = 0;
    rc = close(fd);
    if (!observed(&ctx, "ctl-close", rc, rc == 0)) goto cleanup;
    if (!configure(&ctx, &pcm[open_first], card) || !configure(&ctx, &pcm[!open_first], card)) goto cleanup;
    release(&ctx, &pcm[close_first], 1);
    if (ctx.first_error) goto cleanup;
    if (!state(&ctx, &pcm[!close_first], close_first ? "p-peer-setup" : "c-peer-setup", SNDRV_PCM_STATE_SETUP)) goto cleanup;
    release(&ctx, &pcm[!close_first], 1);
cleanup:
    release(&ctx, &pcm[close_first], 0);
    release(&ctx, &pcm[!close_first], 0);
    if (control >= 0) {
        const int remaining = control;
        control = -1;
        errno = 0;
        int close_rc = close(remaining);
        observed(&ctx, "ctl-close", close_rc, close_rc == 0);
    }
    if (armed) { errno = 0; observed(&ctx, "alarm0", alarm(0), 1); }
    output(&ctx);
    return ctx.first_error ? 2 : 0;
}
