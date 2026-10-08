/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <errno.h>
#include <linux/magic.h>
#include <linux/reboot.h>
#include <stdio.h>
#include <string.h>
#include <sys/reboot.h>
#include <sys/utsname.h>
#include <sys/vfs.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    struct utsname version;
    struct statfs filesystem;
    char executable[256];
    ssize_t length;

    if (argc != 2 || strcmp(argv[1], "--request") != 0) {
        fputs("Only --request is accepted\n", stderr);
        return 2;
    }
    if (geteuid() != 0 || getpid() == 1) {
        fputs("Require root and a non-PID1 process\n", stderr);
        return 2;
    }
    if (uname(&version) < 0) {
        perror("uname");
        return 1;
    }
    if (strcmp(version.release, "5.10.160-rt89-g9f9e9d18574d-dirty") != 0) {
        fputs("Unexpected kernel release\n", stderr);
        return 2;
    }
    length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (length < 0) {
        perror("readlink executable");
        return 1;
    }
    if ((size_t)length >= sizeof(executable) - 1) {
        fputs("Executable path truncated\n", stderr);
        return 2;
    }
    executable[length] = '\0';
    if (strcmp(executable, "/tmp/normal-reboot") != 0) {
        fputs("Unexpected executable path\n", stderr);
        return 2;
    }
    if (statfs("/proc/self/exe", &filesystem) < 0) {
        perror("statfs executable");
        return 1;
    }
    if (filesystem.f_type != TMPFS_MAGIC && filesystem.f_type != RAMFS_MAGIC) {
        fputs("Executable must be in RAM\n", stderr);
        return 2;
    }
    if (puts("NORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN") == EOF || fflush(stdout) != 0) {
        perror("record reboot request");
        return 1;
    }
    if (reboot(LINUX_REBOOT_CMD_RESTART) < 0) {
        perror("normal reboot");
        return 1;
    }
    fputs("Normal reboot returned unexpectedly\n", stderr);
    return 3;
}
