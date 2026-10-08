/* SPDX-License-Identifier: MIT */
/* Appended to byte-identical parameter/identity helpers from pcm-config.c. */
static volatile sig_atomic_t cancelled;
struct transfer_run {
    const char *first;
    int error;
    uint64_t deadline;
    uint64_t frames, samples, zeros;
    unsigned long observed_hw_ptr;
    int card;
    size_t trace_used;
    char trace[262144];
};
static void log_line(struct transfer_run *run, const char *format, ...)
{
    size_t left = sizeof(run->trace)-run->trace_used;
    if (left < 256) {
        if (!run->first) { run->first = "LOG_CAPACITY"; run->error = ENOBUFS; }
        return;
    }
    va_list args;
    va_start(args, format);
    int size = vsnprintf(run->trace+run->trace_used, left, format, args);
    va_end(args);
    if (size < 0 || (size_t)size >= left) {
        if (!run->first) { run->first = "LOG_FORMAT"; run->error = EPROTO; }
        return;
    }
    run->trace_used += size;
}
static void cancel_signal(int signal) { if (!cancelled) cancelled = signal; }
static void fail(struct transfer_run *run, const char *stage, int error)
{
    error = error ? error : EPROTO;
    log_line(run, "PCM_ERROR stage=%s errno=%d\n", stage, error);
    if (!run->first) { run->first = stage; run->error = error; }
}
static int now_ns(uint64_t *value)
{
    struct timespec time;
    if (clock_gettime(CLOCK_MONOTONIC, &time)) return -1;
    if (time.tv_sec < 0 || time.tv_nsec < 0 || time.tv_nsec >= 1000000000L ||
        (uint64_t)time.tv_sec > UINT64_MAX / 1000000000ULL) { errno = EPROTO; return -1; }
    *value = (uint64_t)time.tv_sec * 1000000000ULL + time.tv_nsec;
    return 0;
}
static int remaining_ms(struct transfer_run *run)
{
    uint64_t now;
    if (cancelled) { fail(run, "CANCEL", cancelled == SIGALRM ? ETIMEDOUT : ECANCELED); return 0; }
    /* Keep enough trace space for every cleanup operation/error. */
    if (run->trace_used > sizeof(run->trace)-4096) { fail(run, "LOG_CAPACITY", ENOBUFS); return 0; }
    if (now_ns(&now)) { fail(run, "CLOCK", errno); return 0; }
    if (now >= run->deadline) { fail(run, "DEADLINE", ETIMEDOUT); return 0; }
    uint64_t ms = (run->deadline-now + 999999ULL) / 1000000ULL;
    return ms > 100 ? 100 : (int)ms;
}
static int checked_ioctl(struct transfer_run *run, int fd, unsigned long request, void *arg, const char *stage)
{
    errno = 0;
    int ret = ioctl(fd, request, arg);
    int error = errno;
    log_line(run, "PCM_STAGE name=%s rc=%d errno=%d\n", stage, ret, ret < 0 ? error : 0);
    if (ret) { fail(run, stage, ret < 0 ? error : EPROTO); return 0; }
    return 1;
}
static int normal_close(struct transfer_run *run, int fd, const char *stage)
{
    errno = 0;
    int ret = close(fd), error = errno;
    log_line(run, "PCM_STAGE name=%s rc=%d errno=%d\n", stage, ret, ret < 0 ? error : 0);
    /* Linux releases the fd on EINTR; retry could close a reused descriptor. */
    if (ret) { fail(run, stage, error); return 0; }
    return 1;
}
static int card_strings_valid(const struct snd_ctl_card_info *info)
{
    return text_valid(info->id, sizeof(info->id), 0) &&
           text_valid(info->driver, sizeof(info->driver), 1) &&
           text_valid(info->name, sizeof(info->name), 1) &&
           text_valid(info->longname, sizeof(info->longname), 1) &&
           text_valid(info->mixername, sizeof(info->mixername), 1) &&
           text_valid(info->components, sizeof(info->components), 1);
}
static int selected_card_valid(const struct snd_ctl_card_info *info)
{
    /* Existing real /proc/asound/cards and actual soc_setup_card_name agree. */
    return !strcmp((const char *)info->driver, "rockchip_rk809-") &&
           !strcmp((const char *)info->name, "rockchip,rk809-codec") &&
           !strcmp((const char *)info->longname, "rockchip,rk809-codec");
}
static int character_device(struct transfer_run *run, int fd, const char *stage)
{
    struct stat st;
    errno = 0;
    int ret = fstat(fd, &st), error = errno;
    if (ret || !S_ISCHR(st.st_mode) || major(st.st_rdev) != 116) {
        fail(run, stage, ret ? error : EPROTO); return 0;
    }
    log_line(run, "PCM_STAGE name=%s rc=0 errno=0\n", stage);
    return 1;
}
static int discover_card(struct transfer_run *run)
{
    int found = -1;
    for (int card = 0; card < 32; card++) {
        if (!remaining_ms(run)) return -1;
        char path[64];
        snprintf(path, sizeof(path), "/dev/snd/controlC%d", card);
        errno = 0;
        int fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY), error = errno;
        log_line(run, "PCM_STAGE name=OPEN_CONTROL card=%d rc=%d errno=%d\n", card, fd, fd < 0 ? error : 0);
        if (fd < 0) {
            if (error == ENOENT || error == ENODEV) continue;
            fail(run, "OPEN_CONTROL", error); return -1;
        }
        struct snd_ctl_card_info info;
        memset(&info, 0xff, sizeof(info));
        int valid = character_device(run, fd, "CONTROL_NODE") && remaining_ms(run) &&
            checked_ioctl(run, fd, SNDRV_CTL_IOCTL_CARD_INFO, &info, "CARD_INFO");
        if (valid && (info.card != card || !card_strings_valid(&info))) {
            fail(run, "CARD_IDENTITY", EPROTO); valid = 0;
        }
        int selected = valid && !strcmp((const char *)info.id, "rockchiprk809co");
        if (selected && !selected_card_valid(&info)) { fail(run, "CARD_IDENTITY", EPROTO); valid = 0; }
        int closed = normal_close(run, fd, "CLOSE_CONTROL");
        if (!valid || !closed) return -1;
        if (selected) {
            if (found >= 0) { fail(run, "CARD_AMBIGUOUS", EEXIST); return -1; }
            found = card;
        }
    }
    if (found < 0) fail(run, "CARD_NOT_FOUND", ENODEV);
    return found;
}
static int observe(struct transfer_run *run, int fd, int wanted, const char *stage, struct snd_pcm_status *status)
{
    memset(status, 0, sizeof(*status));
    if (!checked_ioctl(run, fd, SNDRV_PCM_IOCTL_STATUS, status, stage)) return 0;
    log_line(run, "PCM_STATE stage=%s state=%d appl_ptr=%lu hw_ptr=%lu\n", stage, status->state, status->appl_ptr, status->hw_ptr);
    if (status->state != wanted) { fail(run, stage, status->state == SNDRV_PCM_STATE_XRUN ? EPIPE : EPROTO); return 0; }
    return 1;
}
static int wait_ready(struct transfer_run *run, int fd, int stream)
{
    for (;;) {
        int timeout = remaining_ms(run);
        if (!timeout) return 0;
        struct pollfd p = { .fd = fd, .events = stream == SNDRV_PCM_STREAM_CAPTURE ? POLLIN : POLLOUT };
        errno = 0;
        int ret = poll(&p, 1, timeout), error = errno;
        log_line(run, "PCM_STAGE name=POLL rc=%d errno=%d timeout_ms=%d\n", ret, ret < 0 ? error : 0, timeout);
        if (ret < 0) {
            if (error == EINTR) continue;
            fail(run, "POLL", error); return 0;
        }
        if (!ret) continue;
        if (ret != 1 || p.revents & (POLLHUP | POLLNVAL)) { fail(run, "POLL", ENODEV); return 0; }
        if (p.revents & POLLERR) { fail(run, "POLL", EPIPE); return 0; }
        if (!(p.revents & p.events)) { fail(run, "POLL", EPROTO); return 0; }
        return 1;
    }
}
static int transfer_frames(struct transfer_run *run, int fd, int stream, uint64_t count, int prefill)
{
    int16_t buffer[512] = {0};
    uint64_t done = 0;
    while (done < count) {
        if (!remaining_ms(run) || (!prefill && !wait_ready(run, fd, stream))) return 0;
        size_t frames = count-done > 256 ? 256 : (size_t)(count-done);
        size_t bytes = frames * 4;
        errno = 0;
        ssize_t ret = stream == SNDRV_PCM_STREAM_CAPTURE ? read(fd, buffer, bytes) : write(fd, buffer, bytes);
        int error = errno;
        log_line(run, "PCM_STAGE name=%s rc=%zd errno=%d requested_bytes=%zu\n", stream == SNDRV_PCM_STREAM_CAPTURE ? "READ" : "WRITE", ret, ret < 0 ? error : 0, bytes);
        if (ret < 0) {
            if (error == EAGAIN || error == EINTR) { if (!wait_ready(run, fd, stream)) return 0; continue; }
            fail(run, stream == SNDRV_PCM_STREAM_CAPTURE ? "READ" : "WRITE", error); return 0;
        }
        if (!ret || (size_t)ret > bytes || ret % 4) { fail(run, "IO_RESULT", ret ? EPROTO : EIO); return 0; }
        done += (uint64_t)ret / 4;
        run->frames += (uint64_t)ret / 4;
        if (stream == SNDRV_PCM_STREAM_CAPTURE) {
            run->samples += (uint64_t)ret / 2;
            for (ssize_t i = 0; i < ret / 2; i++) run->zeros += buffer[i] == 0;
            memset(buffer, 0, sizeof(buffer));
        }
    }
    return 1;
}
static int number(const char *text, unsigned int min, unsigned int max, unsigned int *value)
{
    if (!*text) return 0;
    for (const char *p = text; *p; p++) if (*p < '0' || *p > '9') return 0;
    char *end;
    errno = 0;
    unsigned long n = strtoul(text, &end, 10);
    if (errno || *end || n < min || n > max) return 0;
    *value = n; return 1;
}
int main(int argc, char **argv)
{
    unsigned int target, timeout;
    if (argc != 9 || strcmp(argv[1], "--card-id") || strcmp(argv[2], "rockchiprk809co") ||
        strcmp(argv[3], "--stream") || (strcmp(argv[4], "playback") && strcmp(argv[4], "capture")) ||
        strcmp(argv[5], "--frames") || !number(argv[6], 1024, 48000, &target) || target % 256 ||
        strcmp(argv[7], "--timeout-ms") || !number(argv[8], 100, 10000, &timeout)) {
        fprintf(stderr, "usage: pcm-transfer --card-id rockchiprk809co --stream playback|capture --frames N --timeout-ms M (N=1024..48000, multiple of256; M=100..10000)\n");
        return 2;
    }
    const int stream = !strcmp(argv[4], "capture") ? SNDRV_PCM_STREAM_CAPTURE : SNDRV_PCM_STREAM_PLAYBACK;
    struct transfer_run run = { .card = -1 };
    int fd = -1, params_attempted = 0, timer_started = 0;
    struct sigaction action;
    sigset_t unblock;
    memset(&action, 0, sizeof(action)); action.sa_handler = cancel_signal;
    if (sigemptyset(&action.sa_mask) || sigemptyset(&unblock) ||
        sigaddset(&unblock, SIGALRM) || sigaddset(&unblock, SIGINT) || sigaddset(&unblock, SIGTERM) ||
        sigaction(SIGALRM, &action, NULL) || sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL) ||
        sigprocmask(SIG_UNBLOCK, &unblock, NULL)) { fail(&run, "SIGNALS", errno); goto cleanup; }
    uint64_t now;
    if (now_ns(&now)) { fail(&run, "CLOCK", errno); goto cleanup; }
    run.deadline = now + (uint64_t)timeout * 1000000ULL;
    struct itimerval timer = { .it_value = { .tv_sec = timeout / 1000, .tv_usec = (timeout % 1000) * 1000 } };
    if (setitimer(ITIMER_REAL, &timer, NULL)) { fail(&run, "TIMER", errno); goto cleanup; }
    timer_started = 1;
    int card = discover_card(&run);
    if (card < 0 || !remaining_ms(&run)) goto cleanup;
    run.card = card;
    char path[64];
    snprintf(path, sizeof(path), "/dev/snd/pcmC%dD0%c", card, stream == SNDRV_PCM_STREAM_CAPTURE ? 'c' : 'p');
    errno = 0;
    fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    log_line(&run, "PCM_STAGE name=OPEN_PCM rc=%d errno=%d\n", fd, fd < 0 ? errno : 0);
    if (fd < 0) { fail(&run, "OPEN_PCM", errno); goto cleanup; }
    if (!character_device(&run, fd, "PCM_NODE") || !remaining_ms(&run)) goto cleanup;
    int version = -1;
    if (!checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_PVERSION, &version, "PVERSION")) goto cleanup;
    if (version != SNDRV_PCM_VERSION) { fail(&run, "PVERSION_IDENTITY", EPROTO); goto cleanup; }
    struct snd_pcm_info info;
    memset(&info, 0xff, sizeof(info));
    if (!remaining_ms(&run) || !checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_INFO, &info, "PCM_INFO")) goto cleanup;
    if (!pcm_info_valid(&info, card, stream)) { fail(&run, "PCM_IDENTITY", EPROTO); goto cleanup; }
    log_line(&run, "PCM_INFO card=%d device=0 subdevice=0 stream=%s id=%s\n", card, argv[4], info.id);
    struct snd_pcm_hw_params params;
    params_any(&params);
    if (!remaining_ms(&run) || !checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_HW_REFINE, &params, "HW_REFINE_CAPS")) goto cleanup;
    if (!caps_valid(&params) || !caps_allow_exact(&params)) { fail(&run, "HW_CAPS", EPROTO); goto cleanup; }
    params_exact(&params);
    if (!remaining_ms(&run) || !checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_HW_REFINE, &params, "HW_REFINE_EXACT")) goto cleanup;
    if (!exact_valid(&params)) { fail(&run, "HW_REFINED_PARAMETERS", EPROTO); goto cleanup; }
    params_exact(&params);
    if (!remaining_ms(&run)) goto cleanup;
    params_attempted = 1;
    if (!checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_HW_PARAMS, &params, "HW_PARAMS")) goto cleanup;
    if (!exact_valid(&params)) { fail(&run, "HW_PARAMETERS", EPROTO); goto cleanup; }
    struct snd_pcm_status status;
    if (!remaining_ms(&run) || !observe(&run, fd, SNDRV_PCM_STATE_SETUP, "STATUS_SETUP", &status)) goto cleanup;
    if (status.appl_ptr || status.hw_ptr) { fail(&run, "SETUP_POINTERS", EPROTO); goto cleanup; }
    struct snd_pcm_sw_params sw = { .tstamp_mode = SNDRV_PCM_TSTAMP_NONE, .period_step = 1,
        .avail_min = 256, .xfer_align = 1, .start_threshold = LONG_MAX, .stop_threshold = 1024,
        .proto = SNDRV_PCM_VERSION, .tstamp_type = SNDRV_PCM_TSTAMP_TYPE_GETTIMEOFDAY };
    if (!remaining_ms(&run) || !checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_SW_PARAMS, &sw, "SW_PARAMS")) goto cleanup;
    if (sw.start_threshold != LONG_MAX || sw.avail_min != 256 || sw.stop_threshold != 1024 ||
        sw.boundary <= 1024 || sw.boundary > LONG_MAX || sw.boundary % 1024) { fail(&run, "SW_PARAMETERS", EPROTO); goto cleanup; }
    if (!remaining_ms(&run) || !checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_PREPARE, NULL, "PREPARE")) goto cleanup;
    if (!remaining_ms(&run) || !observe(&run, fd, SNDRV_PCM_STATE_PREPARED, "STATUS_PREPARED", &status)) goto cleanup;
    if (status.appl_ptr || status.hw_ptr) { fail(&run, "PREPARED_POINTERS", EPROTO); goto cleanup; }
    if (stream == SNDRV_PCM_STREAM_PLAYBACK) {
        if (!transfer_frames(&run, fd, stream, 1024, 1)) goto cleanup;
        if (!remaining_ms(&run) || !observe(&run, fd, SNDRV_PCM_STATE_PREPARED, "STATUS_PREFILLED", &status)) goto cleanup;
        if (status.appl_ptr != 1024 || status.hw_ptr) { fail(&run, "PREFILL_POINTERS", EPROTO); goto cleanup; }
    }
    if (!remaining_ms(&run) || !checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_START, NULL, "START")) goto cleanup;
    if (!remaining_ms(&run) || !observe(&run, fd, SNDRV_PCM_STATE_RUNNING, "STATUS_STARTED", &status)) goto cleanup;
    if (!transfer_frames(&run, fd, stream, target-run.frames, 0) || !wait_ready(&run, fd, stream)) goto cleanup;
    if (!remaining_ms(&run) || !observe(&run, fd, SNDRV_PCM_STATE_RUNNING, "STATUS_TRANSFERRED", &status)) goto cleanup;
    if (status.appl_ptr != target || status.hw_ptr < 256) { fail(&run, "HARDWARE_PROGRESS", EPROTO); goto cleanup; }
    run.observed_hw_ptr = status.hw_ptr;
cleanup:
    /* Cleanup is attempted even after deadline/signal/partial stateful ioctl. */
    if (fd >= 0 && params_attempted) {
        if (checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_DROP, NULL, "DROP")) {
            struct snd_pcm_status status;
            observe(&run, fd, SNDRV_PCM_STATE_SETUP, "STATUS_DROPPED", &status);
        }
        if (checked_ioctl(&run, fd, SNDRV_PCM_IOCTL_HW_FREE, NULL, "HW_FREE")) {
            struct snd_pcm_status status;
            observe(&run, fd, SNDRV_PCM_STATE_OPEN, "STATUS_FREED", &status);
        }
    }
    if (fd >= 0) normal_close(&run, fd, "CLOSE_PCM");
    if (timer_started && !run.first) remaining_ms(&run);
    /* No synchronous output while a PCM fd/transfer can still be active. */
    if (run.trace_used && fwrite(run.trace, 1, run.trace_used, stderr) != run.trace_used)
        fail(&run, "LOG_OUTPUT", errno ? errno : EIO);
    if (run.card >= 0) {
        int printed = printf("PCM_TRANSFER card=%d stream=%s frames=%" PRIu64 " samples=%" PRIu64 " zeros=%" PRIu64 " zero_ppm=%" PRIu64 " observed_hw_ptr=%lu\n", run.card, argv[4], run.frames, run.samples, run.zeros, (uint64_t)(run.samples ? run.zeros * 1000000ULL / run.samples : 0), run.observed_hw_ptr);
        if (printed < 0) fail(&run, "SUMMARY_OUTPUT", errno ? errno : EIO);
    }
    if (timer_started) {
        struct itimerval off = {0};
        if (setitimer(ITIMER_REAL, &off, NULL)) fail(&run, "TIMER_DISARM", errno);
        if (!run.first) remaining_ms(&run);
    }
    if (run.first) {
        fprintf(stderr, "PCM_FIRST_ERROR stage=%s errno=%d frames=%" PRIu64 "\n", run.first, run.error, run.frames);
        return 2;
    }
    /* This marker never permits reboot or proves DMA quiescence. */
    puts("PCM_BOUNDED_IO_COMPLETE_GUARD_STILL_REQUIRED");
    return 0;
}
