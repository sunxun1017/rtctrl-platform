/* SPDX-License-Identifier: MIT */
/* Actual production collector with synthetic cached syscalls; never board I/O. */
#ifndef GUARD_SOURCE
#define GUARD_SOURCE "audio-session-guard.c"
#endif
#define main production_guard_main
#include GUARD_SOURCE
#undef main

static const unsigned int model_profiles[3][16] = {
    {0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 1, 1, 0, 0, 0},
    {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0},
    {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}
};
static const unsigned int tx_indices[] = {5, 6, 7, 8, 9, 11};
static const char *const tx_parents[] = {
    "gpll", "clk_i2s1_8ch_tx_src", "clk_i2s1_8ch_tx_frac",
    "clk_i2s1_8ch_tx", "mclk_i2s1_8ch_tx", "i2s1_mclkout_tx"
};
static unsigned int model_stage;
static unsigned int model_counts[16][3];
static int model_bad_parent = -1;
static int model_missing_parent = -1;
static int model_missing_clock = -1;
static char model_text[2048];
static size_t model_used;
static size_t model_offset;
static int model_opened;
static volatile unsigned int reached_registration;
static volatile unsigned int unexpected_syscall;

uid_t __wrap_getuid(void) { return 0; }
uid_t __wrap_geteuid(void) { return 0; }

char *__wrap_realpath(const char *path, char *resolved)
{
    const char *value = NULL;
    if (!strcmp(path, "/model/cpu")) {
        value = "/sys/devices/platform/fe410000.i2s";
    } else if (!strcmp(path, "/model/dma")) {
        value = "/sys/devices/platform/fe550000.dmac";
    } else if (!strcmp(path, "/sys/devices/platform/fe410000.i2s/driver")) {
        value = "/sys/bus/platform/drivers/rockchip-i2s-tdm";
    } else if (!strcmp(path, "/sys/devices/platform/fe550000.dmac/driver")) {
        value = "/sys/bus/amba/drivers/dma-pl330";
    }
    if (!value) {
        unexpected_syscall++;
        errno = EIO;
        return NULL;
    }
    strcpy(resolved, value);
    return resolved;
}

char *__wrap___realpath_chk(const char *path, char *resolved, size_t size)
{
    if (size < PATH_MAX) {
        unexpected_syscall++;
        errno = ENAMETOOLONG;
        return NULL;
    }
    return __wrap_realpath(path, resolved);
}

int __wrap_statfs(const char *path, struct statfs *fs)
{
    memset(fs, 0, sizeof(*fs));
    if (!strcmp(path, "/model/clock")) {
        fs->f_type = 0x64626720UL;
    } else if (!strcmp(path, "/sys/devices/platform/fe410000.i2s") ||
               !strcmp(path, "/sys/devices/platform/fe550000.dmac")) {
        fs->f_type = 0x62656572UL;
    } else {
        unexpected_syscall++;
        errno = EIO;
        return -1;
    }
    return 0;
}

int __wrap_lstat(const char *path, struct stat *st)
{
    (void)st;
    if (strcmp(path, "/sys/devices/platform/fe410000.i2s/driver") &&
        strcmp(path, "/sys/devices/platform/fe410000.i2s/rk3568_lifecycle_state") &&
        strcmp(path, "/proc/asound/card1") && strcmp(path, "/dev/snd/controlC1")) {
        unexpected_syscall++;
    }
    errno = ENOENT;
    return -1;
}

static int model_input(const char *path)
{
    if (!strcmp(path, "/proc/devices")) {
        reached_registration++;
        errno = EIO;
        return 0;
    }
    if (!strcmp(path, "/sys/devices/platform/fe410000.i2s/rk3568_lifecycle_state")) {
        strcpy(model_text, "version=1 ready=1 error=0 owners=0 open=0 stop_proven=1 stop_reads=2 irq_live=0 irq_drained=1 mclk_leases=0 hclk_lease=1 configuring=0 power_transition=0 shutting_down=0\n");
    } else if (!strcmp(path, "/sys/devices/platform/fe550000.dmac/rk3568_lifecycle_state")) {
        snprintf(model_text, sizeof(model_text), "version=1 ready=1 error=0 stop_proven=1 stop_reads=9 pm_usage=0 leases=0 software=0 queued=0 descriptors=0 allocated=%u\n", model_stage == 2 ? 0 : 2);
    } else if (!strcmp(path, "/sys/devices/platform/fe410000.i2s/power/runtime_status")) {
        strcpy(model_text, "suspended\n");
    } else if (!strcmp(path, "/sys/class/sound/dma_quarantine_bytes")) {
        strcpy(model_text, "0\n");
    } else if (!strcmp(path, "/proc/asound/card1/id")) {
        strcpy(model_text, "rockchiprk809co\n");
    } else if (!strncmp(path, "/proc/asound/card1/pcm0", 23)) {
        strcpy(model_text, "closed\n");
    } else {
        for (unsigned int i = 0; i < 16; i++) {
            char prefix[PATH_MAX];
            snprintf(prefix, sizeof(prefix), "/model/clock/%s/", clock_names[i]);
            if (strncmp(path, prefix, strlen(prefix))) {
                continue;
            }
            const char *leaf = path + strlen(prefix);
            if ((int)i == model_missing_clock && !strcmp(leaf, "clk_enable_count")) {
                errno = ENOENT;
                return 0;
            }
            static const char *const leaves[] = {"clk_enable_count", "clk_prepare_count", "clk_protect_count"};
            for (unsigned int j = 0; j < 3; j++) {
                if (!strcmp(leaf, leaves[j])) {
                    snprintf(model_text, sizeof(model_text), "%u\n", model_counts[i][j]);
                    return 1;
                }
            }
            if (!strcmp(leaf, "clk_parent")) {
                for (unsigned int j = 0; j < 6; j++) {
                    if (i != tx_indices[j]) {
                        continue;
                    }
                    if ((int)j == model_missing_parent) {
                        errno = EIO;
                        return 0;
                    }
                    snprintf(model_text, sizeof(model_text), "%s\n", (int)j == model_bad_parent ? "unexpected_parent" : tx_parents[j]);
                    return 1;
                }
            }
            break;
        }
        unexpected_syscall++;
        errno = EIO;
        return 0;
    }
    return 1;
}

int __wrap_open(const char *path, int flags, ...)
{
    if (model_opened || (flags & O_ACCMODE) != O_RDONLY || !model_input(path)) {
        return -1;
    }
    model_used = strlen(model_text);
    model_offset = 0;
    model_opened = 1;
    return 701;
}

int __wrap___open_2(const char *path, int flags)
{
    return __wrap_open(path, flags);
}

ssize_t __wrap_read(int fd, void *buffer, size_t length)
{
    if (fd != 701 || !model_opened) {
        unexpected_syscall++;
        errno = EBADF;
        return -1;
    }
    size_t remaining = model_used - model_offset;
    if (length > remaining) {
        length = remaining;
    }
    memcpy(buffer, model_text + model_offset, length);
    model_offset += length;
    return (ssize_t)length;
}

ssize_t __wrap___read_chk(int fd, void *buffer, size_t length, size_t capacity)
{
    if (length > capacity) {
        unexpected_syscall++;
        errno = EOVERFLOW;
        return -1;
    }
    return __wrap_read(fd, buffer, length);
}

int __wrap_close(int fd)
{
    if (fd != 701 || !model_opened) {
        unexpected_syscall++;
        errno = EBADF;
        return -1;
    }
    model_opened = 0;
    return 0;
}

static void reset(unsigned int stage, unsigned int profile)
{
    model_stage = stage;
    model_bad_parent = model_missing_parent = model_missing_clock = -1;
    model_opened = 0;
    reached_registration = unexpected_syscall = 0;
    for (unsigned int i = 0; i < 16; i++) {
        model_counts[i][0] = model_counts[i][1] = model_profiles[profile][i];
        model_counts[i][2] = 0;
    }
}

static int clock_gate_passed(void)
{
    char *argv_bound[] = {"guard-stage-model", "bound", "1", "/model/cpu", "/model/dma", "2", "/model/inspector", "/model/clock", NULL};
    char *argv_card[] = {"guard-stage-model", "card-unbound", "1", "/model/cpu", "/model/dma", "2", "/model/clock", NULL};
    char *argv_cpu[] = {"guard-stage-model", "cpu-unbound", "1", "/model/cpu", "/model/dma", "/model/clock", NULL};
    char **argv = model_stage == 0 ? argv_bound : model_stage == 1 ? argv_card : argv_cpu;
    int status = production_guard_main(model_stage == 0 ? 8 : model_stage == 1 ? 7 : 6, argv);
    alarm(0);
    return status == 2 && reached_registration == 1 && unexpected_syscall == 0 && !model_opened;
}

static void report(const char *name, int expected)
{
    int actual = clock_gate_passed();
    printf("%s %u\n", name, actual == expected && !unexpected_syscall);
}

int main(int argc, char **argv)
{
    (void)argv;
    char name[128];
    reset(0, 0);
    report("production-bound-codec-baseline", 1);
    reset(0, 1);
    report("production-bound-reject-missing-codec-baseline", 0);
    if (argc == 2) {
        return 0;
    }
    for (unsigned int stage = 0; stage < 3; stage++) {
        if (stage) {
            reset(stage, stage);
            snprintf(name, sizeof(name), "production-stage-%u-good", stage);
            report(name, 1);
        }
        for (unsigned int profile = 0; profile < 3; profile++) {
            if (stage == profile || (stage == 0 && profile == 1)) {
                continue;
            }
            reset(stage, profile);
            snprintf(name, sizeof(name), "production-stage-%u-reject-profile-%u", stage, profile);
            report(name, 0);
        }
        for (unsigned int clock = 0; clock < 16; clock++) {
            for (unsigned int change = 0; change < 5; change++) {
                reset(stage, stage);
                if (change == 0) {
                    model_counts[clock][0] = model_counts[clock][1] = !model_profiles[stage][clock];
                } else if (change == 1) {
                    model_counts[clock][0] = model_counts[clock][1] = 2;
                } else if (change == 2) {
                    model_counts[clock][0] = model_profiles[stage][clock] + 1;
                } else if (change == 3) {
                    model_counts[clock][1] = model_profiles[stage][clock] + 1;
                } else {
                    model_counts[clock][2] = 1;
                }
                snprintf(name, sizeof(name), "production-stage-%u-clock-%u-change-%u", stage, clock, change);
                report(name, 0);
            }
        }
        for (unsigned int parent = 0; parent < 6; parent++) {
            reset(stage, stage);
            model_bad_parent = (int)parent;
            snprintf(name, sizeof(name), "production-stage-%u-parent-%u-wrong", stage, parent);
            report(name, 0);
            reset(stage, stage);
            model_missing_parent = (int)parent;
            snprintf(name, sizeof(name), "production-stage-%u-parent-%u-read-failure", stage, parent);
            report(name, 0);
        }
        reset(stage, stage);
        model_missing_clock = 0;
        snprintf(name, sizeof(name), "production-stage-%u-count-read-failure", stage);
        report(name, 0);
    }
    return 0;
}
