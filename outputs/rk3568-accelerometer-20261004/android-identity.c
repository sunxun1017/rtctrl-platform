/* SPDX-License-Identifier: GPL-2.0-only */
/* Only for the explicitly audited original Android Image's 24-byte I2C ABI. */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#define LEGACY_I2C_RDWR 0x0707
#define LEGACY_I2C_M_RD 0x0001

struct android_i2c_msg24 {
    uint16_t addr;
    uint16_t flags;
    uint16_t len;
    uint16_t padding;
    uint64_t buffer;
    uint64_t reserved;
};

struct android_i2c_rdwr16 {
    uint64_t messages;
    uint32_t count;
    uint32_t padding;
};

_Static_assert(sizeof(uintptr_t) == 8, "64-bit userspace required");
_Static_assert(sizeof(struct android_i2c_msg24) == 24, "legacy message stride");
_Static_assert(offsetof(struct android_i2c_msg24, addr) == 0, "address offset");
_Static_assert(offsetof(struct android_i2c_msg24, flags) == 2, "flags offset");
_Static_assert(offsetof(struct android_i2c_msg24, len) == 4, "length offset");
_Static_assert(offsetof(struct android_i2c_msg24, padding) == 6, "padding offset");
_Static_assert(offsetof(struct android_i2c_msg24, buffer) == 8, "buffer offset");
_Static_assert(offsetof(struct android_i2c_msg24, reserved) == 16, "reserved offset");
_Static_assert(sizeof(struct android_i2c_rdwr16) == 16, "outer size");
_Static_assert(offsetof(struct android_i2c_rdwr16, messages) == 0, "outer pointer offset");
_Static_assert(offsetof(struct android_i2c_rdwr16, count) == 8, "outer count offset");
_Static_assert(offsetof(struct android_i2c_rdwr16, padding) == 12, "outer padding offset");

int main(int argc, char **argv)
{
    struct android_i2c_msg24 messages[2] = {0};
    struct android_i2c_rdwr16 transfer = {0};
    struct stat device;
    uint8_t index = 0x0f;
    uint8_t identity = 0;
    int result = 2;
    int transferred;
    int fd;

    if (argc != 2 || strcmp(argv[1], "--android-legacy24") != 0) {
        fputs("usage: android-identity --android-legacy24\n", stderr);
        return 2;
    }

    fd = open("/dev/i2c-5", O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY);
    if (fd < 0) {
        perror("android-identity open");
        return 2;
    }
    if (fstat(fd, &device) < 0) {
        perror("android-identity fstat");
        goto out;
    }
    if (!S_ISCHR(device.st_mode) || major(device.st_rdev) != 89 || minor(device.st_rdev) != 5) {
        fputs("android-identity requires character device 89:5\n", stderr);
        goto out;
    }

    messages[0].addr = 0x15;
    messages[0].len = 1;
    messages[0].buffer = (uint64_t)(uintptr_t)&index;
    messages[1].addr = 0x15;
    messages[1].flags = LEGACY_I2C_M_RD;
    messages[1].len = 1;
    messages[1].buffer = (uint64_t)(uintptr_t)&identity;
    transfer.messages = (uint64_t)(uintptr_t)messages;
    transfer.count = 2;

    /* One combined register-index/read transfer. No register value is written. */
    transferred = ioctl(fd, LEGACY_I2C_RDWR, &transfer);
    if (transferred < 0) {
        perror("android-identity I2C_RDWR");
        goto out;
    }
    if (transferred != 2) {
        fprintf(stderr, "android-identity incomplete transfer: %d/2\n", transferred);
        goto out;
    }
    if (identity != 0x05) {
        fprintf(stderr, "ANDROID_LEGACY24_IDENTITY_MISMATCH=0x%02x\n", identity);
        result = 1;
        goto out;
    }
    result = 0;

out:
    if (close(fd) < 0) {
        perror("android-identity close");
        return 2;
    }
    if (result == 0) {
        if (puts("ANDROID_LEGACY24_IDENTITY_OK=0x05") == EOF || fflush(stdout) == EOF) {
            return 2;
        }
    }
    return result;
}
