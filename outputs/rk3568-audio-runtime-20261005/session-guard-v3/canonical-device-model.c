/* SPDX-License-Identifier: MIT */
/* Actual production function; controlled syscall results are models, not sysfs. */
#ifndef GUARD_SOURCE
#define GUARD_SOURCE "audio-session-guard.c"
#endif
#define main production_guard_main
#include GUARD_SOURCE
#undef main

static const char *model_cpu = "/sys/devices/platform/fe410000.i2s";
static const char *model_dma = "/sys/devices/platform/fe550000.dmac";
static unsigned long model_magic = 0x62656572UL;
static int model_realpath_failure;
static int model_statfs_failure;
/* The linker redirects libc after compilation; keep the trace observable. */
static volatile unsigned int driver_calls;

uid_t __wrap_getuid(void)
{
    return 0;
}

uid_t __wrap_geteuid(void)
{
    return 0;
}

char *__wrap_realpath(const char *path, char *resolved)
{
    if (strstr(path, "/driver")) {
        driver_calls++;
        errno = ENOENT;
        return NULL;
    }
    if (model_realpath_failure ||
        (strcmp(path, "/model/cpu") && strcmp(path, "/model/dma"))) {
        errno = ENOENT;
        return NULL;
    }
    strcpy(resolved, !strcmp(path, "/model/cpu") ? model_cpu : model_dma);
    return resolved;
}

/* Ubuntu's fortify wrapper uses this spelling for stack-sized output arrays. */
char *__wrap___realpath_chk(const char *path, char *resolved, size_t size)
{
    if (size < PATH_MAX) {
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
        return 0;
    }
    if (model_statfs_failure) {
        errno = EIO;
        return -1;
    }
    fs->f_type = (long)model_magic;
    return 0;
}

static void result(const char *name, int condition)
{
    printf("%s %u\n", name, !!condition);
}

static void reset(void)
{
    model_cpu = "/sys/devices/platform/fe410000.i2s";
    model_dma = "/sys/devices/platform/fe550000.dmac";
    model_magic = 0x62656572UL;
    model_realpath_failure = 0;
    model_statfs_failure = 0;
    driver_calls = 0;
}

static int production_canonical_reached_driver(void)
{
    char *argv[] = {"guard-model", "cpu-unbound", "1", "/model/cpu", "/model/dma", "/model/clock", NULL};
    int status = production_guard_main(6, argv);
    alarm(0);
    fprintf(stderr, "CANONICAL_MODEL_MAIN status=%d driver_calls=%u\n", status, driver_calls);
    return status == 2 && driver_calls == 1;
}

int main(void)
{
    char resolved[PATH_MAX];
    reset();
    result("production-fixed-dmac-identity", production_canonical_reached_driver());

    reset();
    model_dma = "/sys/devices/platform/fe550000.dma";
    result("production-reject-old-dma-name", !production_canonical_reached_driver() && !driver_calls);

    reset();
    result("canonical-accept-dmac-sysfs", canonical_device("/model/dma", "fe550000.dmac", resolved));
    result("canonical-accept-cpu-sysfs", canonical_device("/model/cpu", "fe410000.i2s", resolved));

    model_dma = "/sys/devices/platform/fe550000.dma";
    result("canonical-reject-old-dma", !canonical_device("/model/dma", "fe550000.dmac", resolved));
    model_dma = "/sys/devices/platform/fe550001.dmac";
    result("canonical-reject-wrong-address", !canonical_device("/model/dma", "fe550000.dmac", resolved));
    model_dma = "/sys/devices/platform/fe550000.dmac-extra";
    result("canonical-reject-extra-suffix", !canonical_device("/model/dma", "fe550000.dmac", resolved));
    model_dma = "/sys/devices/platform/FE550000.dmac";
    result("canonical-reject-uppercase", !canonical_device("/model/dma", "fe550000.dmac", resolved));
    model_dma = "/sys/devices-other/platform/fe550000.dmac";
    result("canonical-reject-prefix-alias", !canonical_device("/model/dma", "fe550000.dmac", resolved));
    model_dma = "/tmp/fe550000.dmac";
    result("canonical-reject-ordinary-directory", !canonical_device("/model/dma", "fe550000.dmac", resolved));

    reset();
    model_magic = 0x01021994UL;
    result("canonical-reject-non-sysfs-magic", !canonical_device("/model/dma", "fe550000.dmac", resolved));
    reset();
    model_realpath_failure = 1;
    result("canonical-reject-realpath-failure", !canonical_device("/model/dma", "fe550000.dmac", resolved));
    reset();
    model_statfs_failure = 1;
    result("canonical-reject-statfs-failure", !canonical_device("/model/dma", "fe550000.dmac", resolved));
    return 0;
}
