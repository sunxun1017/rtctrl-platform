/* Query an explicitly selected tty. No UART data reads/writes or TCSETS. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>

static long baud_number(speed_t value)
{
    static const struct {
        speed_t code;
        long number;
    } speeds[] = {
        {B0, 0}, {B50, 50}, {B75, 75}, {B110, 110}, {B134, 134},
        {B150, 150}, {B200, 200}, {B300, 300}, {B600, 600},
        {B1200, 1200}, {B1800, 1800}, {B2400, 2400}, {B4800, 4800},
        {B9600, 9600}, {B19200, 19200}, {B38400, 38400},
        {B57600, 57600}, {B115200, 115200}, {B230400, 230400},
        {B460800, 460800}, {B500000, 500000}, {B576000, 576000},
        {B921600, 921600}, {B1000000, 1000000}, {B1152000, 1152000},
        {B1500000, 1500000}, {B2000000, 2000000}, {B2500000, 2500000},
        {B3000000, 3000000}, {B3500000, 3500000}, {B4000000, 4000000}
    };
    size_t index;
    for (index = 0; index < sizeof(speeds) / sizeof(speeds[0]); ++index) {
        if (speeds[index].code == value) {
            return speeds[index].number;
        }
    }
    return -1;
}

static const char *boolean_value(int value)
{
    return value ? "true" : "false";
}

static int failure(int error)
{
    fprintf(stderr, "SERIAL_INSPECT_FAILED: errno=%d\n", error);
    return 2;
}

int main(int argc, char **argv)
{
    struct stat metadata;
    struct termios settings;
    int descriptor;
    int error;
    int bits;
    const char *parity = "none";
    long input_baud;
    long output_baud;

    if (argc != 3 || strcmp(argv[1], "--inspect") != 0 || argv[2][0] != '/') {
        fprintf(stderr, "usage: serial-inspect --inspect /absolute/tty/path\n");
        return 2;
    }
    descriptor = open(argv[2], O_RDONLY | O_NOFOLLOW | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (descriptor < 0) {
        return failure(errno);
    }
    if (fstat(descriptor, &metadata) < 0) {
        error = errno;
        close(descriptor);
        return failure(error);
    }
    if (!S_ISCHR(metadata.st_mode)) {
        close(descriptor);
        return failure(ENOTTY);
    }
    if (tcgetattr(descriptor, &settings) < 0) {
        error = errno;
        close(descriptor);
        return failure(error);
    }
    if (close(descriptor) < 0) {
        return failure(errno);
    }
    input_baud = baud_number(cfgetispeed(&settings));
    output_baud = baud_number(cfgetospeed(&settings));
    if (input_baud < 0 || output_baud < 0) {
        return failure(EINVAL);
    }
    switch (settings.c_cflag & CSIZE) {
        case CS5: bits = 5; break;
        case CS6: bits = 6; break;
        case CS7: bits = 7; break;
        case CS8: bits = 8; break;
        default: return failure(EINVAL);
    }
    if (settings.c_cflag & PARENB) {
        parity = (settings.c_cflag & PARODD) ? "odd" : "even";
        if (settings.c_cflag & CMSPAR) {
            parity = (settings.c_cflag & PARODD) ? "mark" : "space";
        }
    }
    printf("{\"input_baud\":%ld,\"output_baud\":%ld,\"data_bits\":%d,"
           "\"stop_bits\":%d,\"parity\":\"%s\",\"hardware_flow\":%s,"
           "\"ixon\":%s,\"ixoff\":%s,\"ixany\":%s,\"cread\":%s,"
           "\"clocal\":%s,\"vmin\":%u,\"vtime\":%u}\n",
           input_baud, output_baud, bits,
           (settings.c_cflag & CSTOPB) ? 2 : 1, parity,
           boolean_value(settings.c_cflag & CRTSCTS),
           boolean_value(settings.c_iflag & IXON),
           boolean_value(settings.c_iflag & IXOFF),
           boolean_value(settings.c_iflag & IXANY),
           boolean_value(settings.c_cflag & CREAD),
           boolean_value(settings.c_cflag & CLOCAL),
           (unsigned int)settings.c_cc[VMIN], (unsigned int)settings.c_cc[VTIME]);
    return ferror(stdout) ? 2 : 0;
}
