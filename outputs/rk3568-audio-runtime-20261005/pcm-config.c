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

static void print_caps(const struct snd_pcm_hw_params *params)
{
    for (unsigned int m = 0; m < 3; m++) {
        printf("PCM_CAP_MASK param=%u bits=", m);
        for (unsigned int i = 0; i < 8; i++) printf("%s%08x", i ? "," : "", params->masks[m].bits[i]);
        printf("\n");
    }
    for (unsigned int i = 0; i < 12; i++) {
        const struct snd_interval *interval = &params->intervals[i];
        printf("PCM_CAP_INTERVAL param=%u min=%u max=%u openmin=%u openmax=%u integer=%u empty=%u\n",
               i + SNDRV_PCM_HW_PARAM_FIRST_INTERVAL, interval->min, interval->max,
               interval->openmin, interval->openmax, interval->integer, interval->empty);
    }
}

/* One attempt per syscall. The first failure survives cleanup failures. */
static void remember_failure(const char **failure, int *saved_errno, const char *stage, int error)
{
    if (!*failure) {
        *failure = stage;
        *saved_errno = error ? error : EPROTO;
    }
}

int main(int argc, char **argv)
{
    if (argc != 6 || strcmp(argv[1], "--configure") || strcmp(argv[2], "--card") ||
        strlen(argv[3]) != 1 || argv[3][0] < '0' || argv[3][0] > '7' ||
        strcmp(argv[4], "--stream") || (strcmp(argv[5], "playback") && strcmp(argv[5], "capture"))) {
        fprintf(stderr, "usage: pcm-config --configure --card N --stream playback|capture (N=0..7)\n");
        return 2;
    }
    const int card = argv[3][0] - '0';
    const int stream = !strcmp(argv[5], "capture") ? SNDRV_PCM_STREAM_CAPTURE : SNDRV_PCM_STREAM_PLAYBACK;
    struct sigaction action;
    sigset_t unblock;
    memset(&action, 0, sizeof(action));
    action.sa_handler = SIG_DFL;
    if (sigemptyset(&action.sa_mask) != 0 || sigaction(SIGALRM, &action, NULL) != 0 ||
        sigemptyset(&unblock) != 0 || sigaddset(&unblock, SIGALRM) != 0 ||
        sigprocmask(SIG_UNBLOCK, &unblock, NULL) != 0) {
        fprintf(stderr, "PCM configuration failed: establish default SIGALRM deadline\n");
        return 2;
    }
    /* A blocked ioctl/close is terminated after five seconds; process exit releases fds.
     * Clear inherited SIG_IGN and unblock SIGALRM before starting this deadline. */
    alarm(5);
    const char *failure = NULL;
    int saved_errno = 0;
    const char *stage = "open control node";
    char path[64];
    snprintf(path, sizeof(path), "/dev/snd/controlC%d", card);
    errno = 0;
    int control_fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    int pcm_fd = -1;
    int configured = 0;
    struct snd_pcm_info info;
    struct snd_pcm_hw_params params;
    struct snd_pcm_status status;
    struct stat st;
    struct snd_ctl_card_info card_info;
    int version = -1;
    if (control_fd < 0) goto failed;
    stage = "control node identity";
    errno = 0;
    if (fstat(control_fd, &st) != 0 || !S_ISCHR(st.st_mode) || major(st.st_rdev) != 116) goto failed;
    stage = "card identity";
    memset(&card_info, 0xff, sizeof(card_info));
    errno = 0;
    if (ioctl(control_fd, SNDRV_CTL_IOCTL_CARD_INFO, &card_info) != 0 || card_info.card != card ||
        memcmp(card_info.id, "rockchiprk809co\0", sizeof(card_info.id))) goto failed;
    stage = "close control node";
    errno = 0;
    if (close(control_fd) != 0) {
        control_fd = -1;
        goto failed;
    }
    control_fd = -1;
    snprintf(path, sizeof(path), "/dev/snd/pcmC%dD0%c", card, stream == SNDRV_PCM_STREAM_CAPTURE ? 'c' : 'p');
    stage = "open PCM node";
    errno = 0;
    pcm_fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    if (pcm_fd < 0) goto failed;
    stage = "PCM node identity";
    errno = 0;
    /* This exact Linux configuration has CONFIG_SND_DYNAMIC_MINORS=y. */
    if (fstat(pcm_fd, &st) != 0 || !S_ISCHR(st.st_mode) || major(st.st_rdev) != 116) goto failed;
    stage = "PCM protocol version";
    errno = 0;
    if (ioctl(pcm_fd, SNDRV_PCM_IOCTL_PVERSION, &version) != 0 ||
        version != SNDRV_PCM_VERSION) goto failed;
    stage = "PCM identity";
    memset(&info, 0xff, sizeof(info));
    errno = 0;
    if (ioctl(pcm_fd, SNDRV_PCM_IOCTL_INFO, &info) != 0 || !pcm_info_valid(&info, card, stream)) goto failed;
    printf("PCM_INFO card=%d device=0 subdevice=0 stream=%s id=%s name=%s\n",
           card, argv[5], info.id, info.name);
    stage = "full hardware refinement";
    params_any(&params);
    errno = 0;
    if (ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_REFINE, &params) != 0 || !caps_valid(&params)) goto failed;
    print_caps(&params);
    stage = "required hardware capabilities";
    errno = 0;
    if (!caps_allow_exact(&params)) goto failed;
    stage = "exact hardware refinement";
    params_exact(&params);
    errno = 0;
    if (ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_REFINE, &params) != 0 || !exact_valid(&params)) goto failed;
    stage = "hardware parameters";
    /* Reset request fields; do not carry kernel output cmask/info/reserved fields. */
    params_exact(&params);
    errno = 0;
    const int params_result = ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_PARAMS, &params);
    configured = params_result >= 0;
    if (params_result != 0 || !exact_valid(&params)) goto failed;
    stage = "configured SETUP state and zero pointers";
    memset(&status, 0, sizeof(status));
    errno = 0;
    if (ioctl(pcm_fd, SNDRV_PCM_IOCTL_STATUS, &status) != 0 ||
        status.state != SNDRV_PCM_STATE_SETUP || status.appl_ptr != 0 || status.hw_ptr != 0) goto failed;
    printf("PCM_CONFIG format=S16_LE access=RW_INTERLEAVED rate=48000 channels=2 period_size=256 periods=4 buffer_size=1024\n");
    printf("PCM_STATE configured=SETUP appl_ptr=0 hw_ptr=0\n");
    stage = "hardware free";
    configured = 0; /* Attempt once, even if the driver reports an error. */
    errno = 0;
    if (ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_FREE) != 0) goto failed;
    stage = "freed OPEN state";
    memset(&status, 0, sizeof(status));
    errno = 0;
    if (ioctl(pcm_fd, SNDRV_PCM_IOCTL_STATUS, &status) != 0 || status.state != SNDRV_PCM_STATE_OPEN) goto failed;
    printf("PCM_STATE freed=OPEN\n");
    goto cleanup;

failed:
    remember_failure(&failure, &saved_errno, stage, errno);
cleanup:
    if (configured) {
        errno = 0;
        if (ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_FREE) != 0) {
            remember_failure(&failure, &saved_errno, "cleanup hardware free", errno);
        }
    }
    if (pcm_fd >= 0) {
        errno = 0;
        if (close(pcm_fd) != 0) remember_failure(&failure, &saved_errno, "close PCM node", errno);
    }
    if (control_fd >= 0) {
        errno = 0;
        if (close(control_fd) != 0) remember_failure(&failure, &saved_errno, "cleanup close control node", errno);
    }
    alarm(0);
    if (failure) {
        fprintf(stderr, "PCM configuration failed: %s (errno=%d)\n", failure, saved_errno);
        return 2;
    }
    /* Neither DMA slave_config nor this marker establishes a DMA transfer. */
    puts("PCM_CONFIGURATION_VERIFIED_NO_START");
    return 0;
}
