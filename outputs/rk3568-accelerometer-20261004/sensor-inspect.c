// SPDX-License-Identifier: MIT
// Fixed address/register reads from the locked MXC6655 source. No register data writes.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    const int require_off = argc == 2 && strcmp(argv[1], "--require-off") == 0;
    if (argc != 1 && !require_off) {
        fprintf(stderr, "usage: sensor-inspect [--require-off]\n");
        return 2;
    }
    int fd = open("/dev/i2c-5", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) {
        perror("open fixed I2C5");
        return 1;
    }
    struct stat metadata;
    int status = 1;
    if (fstat(fd, &metadata) < 0 || !S_ISCHR(metadata.st_mode) ||
        major(metadata.st_rdev) != 89 || minor(metadata.st_rdev) != 5) {
        fprintf(stderr, "fixed I2C5 character device check failed\n");
        goto done;
    }
    uint8_t registers[] = {0x0f, 0x0d, 0x0b};
    uint8_t values[3] = {0};
    for (unsigned int index = 0; index < 3; ++index) {
        struct i2c_msg messages[2] = {
            {.addr = 0x15, .flags = 0, .len = 1, .buf = &registers[index]},
            {.addr = 0x15, .flags = I2C_M_RD, .len = 1, .buf = &values[index]}};
        struct i2c_rdwr_ioctl_data transfer = {.msgs = messages, .nmsgs = 2};
        const int count = ioctl(fd, I2C_RDWR, &transfer);
        if (count != 2) {
            fprintf(stderr, "address=0x15 register=0x%02x transfer=%d errno=%d (%s)\n",
                    registers[index], count, count < 0 ? errno : 0,
                    count < 0 ? strerror(errno) : "short I2C transfer");
            goto done;
        }
        printf("address=0x15 register=0x%02x value=0x%02x\n", registers[index], values[index]);
    }
    if (values[0] != 0x05) {
        fprintf(stderr, "WHO_AM_I differs from locked driver expectation 0x05\n");
        status = 3;
        goto done;
    }
    if (require_off && (!(values[1] & 1) || (values[2] & 1))) {
        fprintf(stderr, "power down / DRDY disabled check failed\n");
        status = 4;
        goto done;
    }
    puts("SENSOR_IDENTITY_READ_COMPLETE");
    status = 0;
done:
    if (close(fd) < 0) {
        perror("close fixed I2C5");
        status = 1;
    }
    return status;
}
