// SPDX-License-Identifier: MIT
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/spi/spidev.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

_Static_assert(sizeof(struct spi_ioc_transfer) == 32, "SPI UAPI transfer size");
_Static_assert(offsetof(struct spi_ioc_transfer, tx_buf) == 0, "SPI TX offset");
_Static_assert(offsetof(struct spi_ioc_transfer, rx_buf) == 8, "SPI RX offset");
_Static_assert(offsetof(struct spi_ioc_transfer, len) == 16, "SPI length offset");
_Static_assert(offsetof(struct spi_ioc_transfer, speed_hz) == 20, "SPI speed offset");
_Static_assert(offsetof(struct spi_ioc_transfer, bits_per_word) == 26, "SPI bits offset");
_Static_assert(offsetof(struct spi_ioc_transfer, cs_change) == 27, "SPI CS offset");
_Static_assert(offsetof(struct spi_ioc_transfer, pad) == 31, "SPI padding offset");

static void system_error(const char *operation)
{
    int saved_errno = errno;
    fprintf(stderr, "%s: errno=%d (%s)\n", operation, saved_errno, strerror(saved_errno));
}

static int read_configuration(int fd, unsigned long request, void *value, const char *name)
{
    int result = ioctl(fd, request, value);
    if (result < 0) {
        system_error(name);
        return -1;
    }
    if (result != 0) {
        fprintf(stderr, "%s: unexpected ioctl return=%d, expected=0\n", name, result);
        return -1;
    }
    return 0;
}

static int check_configuration(int fd)
{
    uint8_t mode = 0;
    uint8_t bits = 0;
    uint32_t speed = 0;
    uint8_t lsb_first = 0;
    if (read_configuration(fd, SPI_IOC_RD_MODE, &mode, "SPI_IOC_RD_MODE") < 0) {
        return -1;
    }
    if (mode != SPI_MODE_3) {
        fprintf(stderr, "SPI mode=0x%02x, expected=0x03\n", mode);
        return -1;
    }
    if (read_configuration(fd, SPI_IOC_RD_BITS_PER_WORD, &bits, "SPI_IOC_RD_BITS_PER_WORD") < 0) {
        return -1;
    }
    if (bits != 8) {
        fprintf(stderr, "SPI bits_per_word=%u, expected=8\n", bits);
        return -1;
    }
    if (read_configuration(fd, SPI_IOC_RD_MAX_SPEED_HZ, &speed, "SPI_IOC_RD_MAX_SPEED_HZ") < 0) {
        return -1;
    }
    if (speed != 100000) {
        fprintf(stderr, "SPI max_speed_hz=%u, expected=100000\n", speed);
        return -1;
    }
    if (read_configuration(fd, SPI_IOC_RD_LSB_FIRST, &lsb_first, "SPI_IOC_RD_LSB_FIRST") < 0) {
        return -1;
    }
    if (lsb_first != 0) {
        fprintf(stderr, "SPI lsb_first=%u, expected=0\n", lsb_first);
        return -1;
    }
    return 0;
}

static int read_identity_register(int fd, uint8_t reg, uint8_t *value)
{
    // Microchip DS00001620C Figure 4-7: one CS assertion, four full-duplex bytes.
    const uint8_t tx[4] = {0x7d, reg, 0x7f, 0x7f};
    uint8_t rx[4] = {0};
    struct spi_ioc_transfer transfer = {0};
    transfer.tx_buf = (uintptr_t)tx;
    transfer.rx_buf = (uintptr_t)rx;
    transfer.len = sizeof(tx);
    transfer.speed_hz = 100000;
    transfer.bits_per_word = 8;
    int result = ioctl(fd, SPI_IOC_MESSAGE(1), &transfer);
    if (result < 0) {
        int saved_errno = errno;
        fprintf(stderr, "SPI identity read register=0x%02x: errno=%d (%s)\n",
                reg, saved_errno, strerror(saved_errno));
        return -1;
    }
    if (result != 4) {
        fprintf(stderr, "SPI identity read register=0x%02x: transferred=%d, expected=4\n", reg, result);
        return -1;
    }
    *value = rx[3];
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--inspect") != 0) {
        fprintf(stderr, "usage: cap1188-inspect --inspect\n");
        return 2;
    }
    // Opening the controller and making read transactions can affect hardware state.
    int fd = open("/dev/spidev3.0", O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY);
    if (fd < 0) {
        system_error("open /dev/spidev3.0");
        return 2;
    }
    int status = 2;
    struct stat st;
    uint8_t product = 0;
    uint8_t manufacturer = 0;
    uint8_t revision = 0;
    if (fstat(fd, &st) < 0) {
        system_error("fstat /dev/spidev3.0");
        goto finish;
    }
    // spidev allocates minors dynamically; board runtime must align its sysfs/dev identity.
    if (!S_ISCHR(st.st_mode) || major(st.st_rdev) != 153) {
        fprintf(stderr, "/dev/spidev3.0 must be a character device with major=153\n");
        goto finish;
    }
    if (check_configuration(fd) < 0) {
        goto finish;
    }
    if (read_identity_register(fd, 0xfd, &product) < 0 ||
        read_identity_register(fd, 0xfe, &manufacturer) < 0 ||
        read_identity_register(fd, 0xff, &revision) < 0) {
        goto finish;
    }
    if (product != 0x50 || manufacturer != 0x5d) {
        fprintf(stderr, "CAP1188 identity mismatch: product=0x%02x manufacturer=0x%02x\n",
                product, manufacturer);
        status = 1;
        goto finish;
    }
    status = 0;
finish:
    if (close(fd) < 0) {
        system_error("close /dev/spidev3.0");
        status = 2;
    }
    if (status == 0) {
        printf("CAP1188_IDENT product=0x%02x manufacturer=0x%02x revision=0x%02x\n",
               product, manufacturer, revision);
        puts("CAP1188_IDENTITY_VERIFIED");
    }
    return status;
}
