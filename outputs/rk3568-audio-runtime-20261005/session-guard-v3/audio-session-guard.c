/* SPDX-License-Identifier: MIT */
/* Read-only session boundary checks. This program has no PCM or PM ioctls. */
#define _GNU_SOURCE
#include "guard-parser.h"
#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

enum { SMALL = 2048, REPORT = 32768, CLOCK = 262144, PROCESSES = 4096 };
struct snapshot {
    char cpu[SMALL];
    char dma[SMALL];
    char quarantine[SMALL];
    char clocks[CLOCK];
    char devices[32768];
    unsigned int uio_major;
    char process_set[PROCESSES * 48];
};

static int reject(const char *operation)
{
    fprintf(stderr, "AUDIO_SESSION_REJECTED operation=%s errno=%d\n", operation, errno);
    return 0;
}

static int read_text(const char *path, char *data, size_t capacity)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | O_NOCTTY);
    if (fd < 0) {
        return reject(path);
    }
    size_t used = 0;
    int good = 1;
    for (;;) {
        ssize_t count = read(fd, data + used, capacity - used - 1);
        if (count < 0) {
            good = reject(path);
            break;
        }
        if (!count) {
            break;
        }
        if (memchr(data + used, 0, (size_t)count)) {
            good = reject("embedded NUL");
            break;
        }
        used += (size_t)count;
        if (used + 1 == capacity) {
            good = reject("input capacity");
            break;
        }
    }
    data[used] = 0;
    if (close(fd)) {
        good = reject("read close");
    }
    return good && used;
}

static int child_path(char *out, size_t size, const char *device, const char *leaf)
{
    int length = snprintf(out, size, "%s/%s", device, leaf);
    return length > 0 && (size_t)length < size;
}

static int attribute(const char *device, const char *leaf, char *out, size_t size)
{
    char path[PATH_MAX];
    return child_path(path, sizeof(path), device, leaf) && read_text(path, out, size);
}

static int missing(const char *path)
{
    struct stat st;
    if (lstat(path, &st) == 0 || errno != ENOENT) {
        return reject("expected missing object");
    }
    return 1;
}

static int driver_check(const char *device, const char *expected, int bound)
{
    char path[PATH_MAX], resolved[PATH_MAX];
    if (!child_path(path, sizeof(path), device, "driver")) {
        return reject("driver path");
    }
    if (!bound) {
        return missing(path);
    }
    if (!realpath(path, resolved) || strcmp(resolved, expected)) {
        return reject("driver identity");
    }
    return 1;
}

static int canonical_device(const char *input, const char *name, char *out)
{
    struct statfs fs;
    if (!realpath(input, out) || strncmp(out, "/sys/devices/", 13) ||
        strcmp(strrchr(out, '/') + 1, name) || statfs(out, &fs) ||
        (unsigned long)fs.f_type != 0x62656572UL) {
        return reject("canonical sysfs device");
    }
    return 1;
}

static int decimal(const char *text);

static int cached_clocks(const char *directory, char *out, size_t capacity)
{
    static const char *const leaves[] = {"clk_enable_count", "clk_prepare_count", "clk_protect_count"};
    char path[PATH_MAX], text[SMALL];
    size_t used = 0;
    out[0] = 0;
    for (unsigned int i = 0; i < 16; i++) {
        unsigned int values[3];
        for (unsigned int j = 0; j < 3; j++) {
            int length = snprintf(path, sizeof(path), "%s/%s/%s", directory, clock_names[i], leaves[j]);
            if (length < 0 || (size_t)length >= sizeof(path) || !read_text(path, text, sizeof(text))) {
                return 0;
            }
            /* debugfs u32 has decimal canonical data with one final LF. */
            size_t digits = strlen(text);
            if (digits < 2 || digits > 11 || text[digits - 1] != '\n') {
                return reject("cached clock count syntax");
            }
            text[digits - 1] = 0;
            if (!decimal(text) || (text[0] == '0' && text[1])) {
                return reject("cached clock count syntax");
            }
            errno = 0;
            unsigned long value = strtoul(text, NULL, 10);
            if (errno || value > UINT_MAX) {
                return reject("cached clock count range");
            }
            values[j] = (unsigned int)value;
        }
        int length = snprintf(out + used, capacity - used, "%s enable=%u prepare=%u protect=%u\n",
                              clock_names[i], values[0], values[1], values[2]);
        if (length < 0 || (size_t)length >= capacity - used) {
            return reject("clock output capacity");
        }
        used += (size_t)length;
    }
    return 1;
}

static int decimal(const char *text)
{
    if (!*text) {
        return 0;
    }
    for (; *text; text++) {
        if (*text < '0' || *text > '9') {
            return 0;
        }
    }
    return 1;
}

static int process_compare(const void *a, const void *b)
{
    return strcmp(a, b);
}

/* All visible processes, including aliases to sound major 116/OSS 14. */
static int fd_scan(char *inventory, size_t capacity, unsigned int uio_major)
{
    char identities[PROCESSES][48];
    size_t count = 0;
    DIR *proc = opendir("/proc");
    if (!proc) {
        return reject("proc visibility");
    }
    int good = 1;
    struct dirent *entry;
    errno = 0;
    while ((entry = readdir(proc))) {
        if (!decimal(entry->d_name)) {
            continue;
        }
        if (count == PROCESSES) {
            good = reject("process capacity");
            break;
        }
        char path[PATH_MAX], stat_text[8192];
        snprintf(path, sizeof(path), "/proc/%s/stat", entry->d_name);
        if (!read_text(path, stat_text, sizeof(stat_text))) {
            good = 0;
            break;
        }
        char *tail = strrchr(stat_text, ')');
        if (!tail || tail[1] != ' ') {
            good = reject("process stat");
            break;
        }
        /* Field 22 is starttime; state (field 3) follows the last ')'. */
        tail += 2;
        char *save = NULL, *part = strtok_r(tail, " \n", &save);
        for (unsigned int field = 3; field < 22 && part; field++) {
            part = strtok_r(NULL, " \n", &save);
        }
        if (!part || !decimal(part) || strlen(part) > 20 || strlen(entry->d_name) > 20) {
            good = reject("process identity");
            break;
        }
        snprintf(identities[count++], sizeof(identities[0]), "%.20s:%.20s", entry->d_name, part);
        snprintf(path, sizeof(path), "/proc/%s/fd", entry->d_name);
        DIR *fds = opendir(path);
        if (!fds) {
            good = reject("FD visibility");
            break;
        }
        struct dirent *fd;
        errno = 0;
        while ((fd = readdir(fds))) {
            if (!decimal(fd->d_name)) {
                continue;
            }
            struct stat st;
            char target[PATH_MAX];
            ssize_t length = readlinkat(dirfd(fds), fd->d_name, target, sizeof(target) - 1);
            if (length < 0 || (size_t)length == sizeof(target) - 1 ||
                fstatat(dirfd(fds), fd->d_name, &st, 0)) {
                good = reject("FD race or inaccessible target");
                break;
            }
            target[length] = 0;
            if (related_fd(S_ISCHR(st.st_mode), major(st.st_rdev), minor(st.st_rdev), target, uio_major)) {
                fprintf(stderr, "AUDIO_FD_BUSY pid=%s fd=%s target=%s\n",
                        entry->d_name, fd->d_name, target);
                good = 0;
                break;
            }
            errno = 0;
        }
        if (errno && good) {
            good = reject("FD enumeration");
        }
        if (closedir(fds)) {
            good = reject("FD enumeration close");
        }
        if (!good) {
            break;
        }
        errno = 0;
    }
    if (errno && good) {
        good = reject("process enumeration");
    }
    if (closedir(proc)) {
        good = reject("process enumeration close");
    }
    if (!good) {
        return 0;
    }
    qsort(identities, count, sizeof(identities[0]), process_compare);
    inventory[0] = 0;
    size_t used = 0;
    for (size_t i = 0; i < count; i++) {
        int length = snprintf(inventory + used, capacity - used, "%s\n", identities[i]);
        if (length < 0 || (size_t)length >= capacity - used) {
            return reject("inventory capacity");
        }
        used += (size_t)length;
    }
    return 1;
}

static int inspector(const char *program, unsigned int card, char *report)
{
    int executable = open(program, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY);
    struct stat st;
    int pipefd[2];
    if (executable < 0 || fstat(executable, &st) || !S_ISREG(st.st_mode) ||
        st.st_uid || (st.st_mode & 022) || !(st.st_mode & 0111)) {
        if (executable >= 0) {
            close(executable);
        }
        return reject("inspector executable identity/permissions");
    }
    if (pipe2(pipefd, O_CLOEXEC)) {
        close(executable);
        return reject("inspector pipe");
    }
    pid_t child = fork();
    if (child == 0) {
        char number[2] = {(char)('0' + card), 0};
        char *const argv[] = {(char *)program, "--inspect", "--card", number, NULL};
        char *const env[] = {"PATH=/bin", "LC_ALL=C", NULL};
        if (dup2(pipefd[1], 1) < 0 || dup2(pipefd[1], 2) < 0) {
            _exit(126);
        }
        close(pipefd[0]);
        close(pipefd[1]);
        fexecve(executable, argv, env);
        _exit(127);
    }
    int good = child > 0;
    close(executable);
    close(pipefd[1]);
    size_t used = 0;
    while (good) {
        ssize_t count = read(pipefd[0], report + used, REPORT - used - 1);
        if (count < 0) {
            good = reject("inspector output read");
            break;
        }
        if (!count) {
            break;
        }
        if (memchr(report + used, 0, (size_t)count)) {
            good = reject("inspector embedded NUL");
            break;
        }
        used += (size_t)count;
        if (used + 1 == REPORT) {
            good = reject("inspector capacity");
            break;
        }
    }
    report[used] = 0;
    if (close(pipefd[0])) {
        good = reject("inspector pipe close");
    }
    int status = 0;
    if (child <= 0 || waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) {
        good = reject("inspector exit");
    }
    return good;
}

static int collect(struct snapshot *s, const char *cpu, const char *dma,
                   const char *clocks, unsigned int card, int stage, unsigned int allocation)
{
    char text[SMALL], path[PATH_MAX];
    if (!driver_check(dma, "/sys/bus/amba/drivers/dma-pl330", 1) ||
        !driver_check(cpu, "/sys/bus/platform/drivers/rockchip-i2s-tdm", stage != 2)) {
        return 0;
    }
    if (stage == 2) {
        if (!child_path(path, sizeof(path), cpu, "rk3568_lifecycle_state") || !missing(path)) {
            return 0;
        }
        strcpy(s->cpu, "CPU_COMPONENT_UNBOUND\n");
    } else if (!attribute(cpu, "rk3568_lifecycle_state", s->cpu, sizeof(s->cpu)) ||
               !cpu_valid(s->cpu, 1) ||
               !attribute(cpu, "power/runtime_status", text, sizeof(text)) || strcmp(text, "suspended\n")) {
        return reject("CPU idle proof");
    }
    if (!attribute(dma, "rk3568_lifecycle_state", s->dma, sizeof(s->dma)) ||
        !dma_valid(s->dma, stage == 2 ? 0 : allocation) ||
        !read_text("/sys/class/sound/dma_quarantine_bytes", s->quarantine, sizeof(s->quarantine)) ||
        !quarantine_valid(s->quarantine) ||
        !cached_clocks(clocks, s->clocks, sizeof(s->clocks))) {
        return reject("DMA/quarantine/clock proof");
    }
    char clock_copy[CLOCK];
    strcpy(clock_copy, s->clocks);
    if (!clock_valid(clock_copy, stage != 2)) {
        return reject("clock reference proof");
    }
    snprintf(path, sizeof(path), "/proc/asound/card%u", card);
    if (stage) {
        if (!missing(path)) {
            return 0;
        }
        snprintf(path, sizeof(path), "/dev/snd/controlC%u", card);
        if (!missing(path)) {
            return 0;
        }
    } else {
        char card_path[PATH_MAX];
        snprintf(card_path, sizeof(card_path), "/proc/asound/card%u/id", card);
        if (!read_text(card_path, text, sizeof(text)) || strcmp(text, "rockchiprk809co\n")) {
            return reject("proc card identity");
        }
        for (unsigned int direction = 0; direction < 2; direction++) {
            for (unsigned int field = 0; field < 2; field++) {
                snprintf(card_path, sizeof(card_path), "/proc/asound/card%u/pcm0%c/sub0/%s",
                         card, direction ? 'c' : 'p', field ? "hw_params" : "status");
                if (!read_text(card_path, text, sizeof(text)) || strcmp(text, "closed\n")) {
                    return reject("PCM not closed");
                }
            }
        }
    }
    char device_copy[32768];
    unsigned int uio_major;
    if (!read_text("/proc/devices", s->devices, sizeof(s->devices))) {
        return reject("character registration read");
    }
    strcpy(device_copy, s->devices);
    if (!devices_valid(device_copy, &uio_major)) {
        return reject("character registration syntax/ambiguity");
    }
    s->uio_major = uio_major;
    if (!fd_scan(s->process_set, sizeof(s->process_set), uio_major)) {
        return 0;
    }
    /* Also bracket each FD enumeration, not just the whole session. */
    if (!read_text("/proc/devices", device_copy, sizeof(device_copy)) ||
        !stable_valid(s->devices, device_copy)) {
        return reject("registration changed during FD scan");
    }
    return 1;
}

int main(int argc, char **argv)
{
    int stage = argc > 1 && !strcmp(argv[1], "bound") ? 0 :
                argc > 1 && !strcmp(argv[1], "card-unbound") ? 1 :
                argc > 1 && !strcmp(argv[1], "cpu-unbound") ? 2 : -1;
    if (stage < 0 || argc != (stage == 0 ? 8 : stage == 1 ? 7 : 6) ||
        strlen(argv[2]) != 1 || argv[2][0] < '0' || argv[2][0] > '7' ||
        (stage != 2 && (strlen(argv[5]) != 1 || argv[5][0] < '0' || argv[5][0] > '8'))) {
        fprintf(stderr, "usage: audio-session-guard bound CARD CPU_DEVICE DMA_DEVICE ALLOC INSPECT DEBUG_CLK_DIR\n"
                        "       audio-session-guard card-unbound CARD CPU_DEVICE DMA_DEVICE ALLOC DEBUG_CLK_DIR\n"
                        "       audio-session-guard cpu-unbound CARD CPU_DEVICE DMA_DEVICE DEBUG_CLK_DIR\n");
        return 2;
    }
    struct sigaction action = {0};
    sigset_t unblock;
    action.sa_handler = SIG_DFL;
    sigemptyset(&action.sa_mask);
    sigemptyset(&unblock);
    sigaddset(&unblock, SIGALRM);
    if (getuid() || geteuid() || sigaction(SIGALRM, &action, NULL) ||
        sigprocmask(SIG_UNBLOCK, &unblock, NULL)) {
        reject("root/deadline setup");
        return 2;
    }
    alarm(15);
    char cpu[PATH_MAX], dma[PATH_MAX], report[REPORT] = {0}, second_report[REPORT] = {0};
    unsigned int card = (unsigned int)(argv[2][0] - '0');
    unsigned int allocation = stage == 2 ? 0 : (unsigned int)(argv[5][0] - '0');
    const char *clocks = argv[stage == 0 ? 7 : stage == 1 ? 6 : 5];
    struct statfs clock_fs;
    if (clocks[0] != '/' || statfs(clocks, &clock_fs) || (unsigned long)clock_fs.f_type != 0x64626720UL ||
        !canonical_device(argv[3], "fe410000.i2s", cpu) ||
        !canonical_device(argv[4], "fe550000.dmac", dma)) {
        reject("fixed device/clock path");
        return 2;
    }
    static struct snapshot first, second;
    if (!collect(&first, cpu, dma, clocks, card, stage, allocation)) {
        return 2;
    }
    if (stage == 0) {
        if (!inspector(argv[6], card, report)) {
            return 2;
        }
        char copy[REPORT];
        strcpy(copy, report);
        if (!inspect_valid(copy, card)) {
            reject("cached control OFF/MIC OFF/Resume OFF");
            return 2;
        }
        if (!inspector(argv[6], card, second_report)) {
            return 2;
        }
        strcpy(copy, second_report);
        if (!inspect_valid(copy, card) || !stable_valid(report, second_report)) {
            reject("unstable cached controls");
            return 2;
        }
    }
    if (!collect(&second, cpu, dma, clocks, card, stage, allocation) ||
        !stable_valid(first.cpu, second.cpu) || !stable_valid(first.dma, second.dma) ||
        !stable_valid(first.quarantine, second.quarantine) ||
        !stable_valid(first.clocks, second.clocks) ||
        !stable_valid(first.devices, second.devices) ||
        !stable_valid(first.process_set, second.process_set)) {
        reject("unstable snapshot");
        return 2;
    }
    /* Output follows all checks; each subsequent action still needs a fresh gate. */
    printf("AUDIO_CPU %s", second.cpu);
    printf("AUDIO_DMA %s", second.dma);
    printf("AUDIO_QUARANTINE %s", second.quarantine);
    printf("AUDIO_PROCESSES_BEGIN\n%sAUDIO_PROCESSES_END\n", second.process_set);
    printf("AUDIO_CHARACTER_REGISTRATIONS_BEGIN\n%sAUDIO_CHARACTER_REGISTRATIONS_END\n", second.devices);
    printf("AUDIO_UIO_REGISTRATION present=%u major=%u\n", !!second.uio_major, second.uio_major);
    printf("AUDIO_CLOCKS_BEGIN\n%sAUDIO_CLOCKS_END\n", second.clocks);
    if (stage == 0) {
        printf("%s", report);
    }
    if (printf("AUDIO_SESSION_IDLE_VERIFIED stage=%s allocated=%u board_start_permission=0 reboot_permission=0\n",
               argv[1], allocation) < 0 || fflush(stdout) || ferror(stdout)) {
        reject("evidence output");
        return 2;
    }
    alarm(0);
    return 0;
}
