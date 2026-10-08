// Diagnostic probe for the fingerprinted original 4.19 MCU driver only.
// ioctl 0xc0 copies cached kernel bytes; it does not read the physical MCU.
// This is not a production MCU driver, motion API, or watchdog implementation.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 2 || strcmp(argv[1], "/dev/McuCom") != 0) {
        fprintf(stderr, "Usage: %s /dev/McuCom (verified original driver only)\n", argv[0]);
        return 64;
    }

    int fd = open(argv[1], O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) {
        perror("open cached MCU interface");
        return 1;
    }

    struct stat info;
    if (fstat(fd, &info) < 0 || !S_ISCHR(info.st_mode)) {
        fprintf(stderr, "MCU interface must be a character device\n");
        close(fd);
        return 1;
    }

    // The vendor request does not encode its buffer length in the ioctl number.
    // The full 65-byte readable/writable buffer is required by this exact ABI.
    unsigned char buffer[65] = {0};
    if (ioctl(fd, 0xc0UL, buffer) < 0) {
        int failure = errno;
        close(fd);
        errno = failure;
        perror("read cached MCU information");
        return 1;
    }

    if (close(fd) < 0) {
        perror("close cached MCU interface");
        return 1;
    }

    // Byte meanings are deliberately not invented from a successful syscall.
    printf("MCU_CACHE_BYTES=");
    for (size_t i = 32; i < 38; ++i) {
        printf("%02x", buffer[i]);
    }
    printf("\nSOURCE=kernel-cache; physical MCU status not queried\n");
    return 0;
}
