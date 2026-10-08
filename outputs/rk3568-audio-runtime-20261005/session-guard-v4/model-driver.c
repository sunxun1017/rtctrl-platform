/* SPDX-License-Identifier: MIT */
/* Offline fixtures only. This executable is never a board accessory. */
#define _GNU_SOURCE
#include "guard-parser.h"

static int load(const char *path, char *text, size_t capacity)
{
    FILE *input = fopen(path, "rb");
    if (!input) {
        return 0;
    }
    size_t length = fread(text, 1, capacity - 1, input);
    int good = !ferror(input) && feof(input) && !memchr(text, 0, length);
    if (fclose(input)) {
        good = 0;
    }
    text[length] = 0;
    return good;
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        return 2;
    }
    FILE *cases = fopen(argv[1], "r");
    if (!cases) {
        return 2;
    }
    char line[4096], first[32768], second[32768];
    while (fgets(line, sizeof(line), cases)) {
        char name[128], kind[32], file[1024], extra[1024];
        unsigned int argument;
        int consumed = 0;
        if (sscanf(line, "%127s %31s %u %1023s %1023s%n", name, kind, &argument,
                   file, extra, &consumed) != 5 || strcmp(line + consumed, "\n") ||
            !load(file, first, sizeof(first))) {
            return 2;
        }
        int result = 0;
        if (!strcmp(kind, "cpu")) {
            result = cpu_valid(first, argument);
        } else if (!strcmp(kind, "dma")) {
            result = dma_valid(first, argument);
        } else if (!strcmp(kind, "quarantine")) {
            result = quarantine_valid(first);
        } else if (!strcmp(kind, "inspect")) {
            result = inspect_valid(first, argument);
        } else if (!strcmp(kind, "clocks")) {
            result = clock_valid(first, argument);
        } else if (!strcmp(kind, "stable")) {
            if (!load(extra, second, sizeof(second))) {
                return 2;
            }
            result = stable_valid(first, second);
        } else if (!strcmp(kind, "fd")) {
            unsigned int character, major_number, minor_number;
            char target[1024];
            if (sscanf(first, "%u %u %u %1023s", &character, &major_number,
                       &minor_number, target) != 4) {
                return 2;
            }
            result = !related_fd(character, major_number, minor_number, target, argument);
        } else if (!strcmp(kind, "devices")) {
            unsigned int actual;
            result = devices_valid(first, &actual) && actual == argument;
        } else if (!strcmp(kind, "devices-read")) {
            unsigned int actual;
            result = load(extra, second, sizeof(second)) &&
                     devices_valid(second, &actual) && actual == argument;
        } else if (!strcmp(kind, "registered-fd")) {
            unsigned int character, major_number, minor_number, actual;
            char target[1024];
            if (sscanf(first, "%u %u %u %1023s", &character, &major_number,
                       &minor_number, target) != 4) {
                return 2;
            }
            result = load(extra, second, sizeof(second)) && devices_valid(second, &actual) &&
                     !related_fd(character, major_number, minor_number, target, actual);
        } else {
            return 2;
        }
        printf("%s %d\n", name, result);
    }
    int failed = ferror(cases) || fclose(cases);
    return failed ? 2 : 0;
}
