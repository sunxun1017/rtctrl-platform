// SPDX-License-Identifier: MIT
// Check CRNG readiness once without blocking or exposing a random byte.
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/random.h>

int main(int argc, char **argv) {
    if (argc != 1 && !(argc == 2 && strcmp(argv[1], "--check") == 0)) {
        fputs("Usage: entropy-check [--check]\n", stderr);
        return 2;
    }

    unsigned char byte;
    ssize_t length = getrandom(&byte, 1, GRND_NONBLOCK);
    if (length == 1) {
        puts("CRNG_READY");
        return 0;
    }
    if (length == -1 && errno == EAGAIN) {
        puts("CRNG_NOT_READY");
        return 1;
    }
    puts("CRNG_CHECK_FAILED");
    return 2;
}
