#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the actual inspect main with intercepted device calls, never SPI hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "cap1188-inspect.c"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
WRAPPERS = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/spi/spidev.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

extern int inspect_main(int argc, char **argv);
extern int __real_puts(const char *s);
static const char *scenario;
static int opened, stated, configs, messages, closed, reports, markers, violations;
static char sequence[128];
static void event(char c)
{
    size_t length = strlen(sequence);
    if (length + 1 >= sizeof(sequence)) {
        abort();
    }
    sequence[length] = c;
    sequence[length + 1] = 0;
}
static int is(const char *name)
{
    return strcmp(scenario, name) == 0;
}
int __wrap_open(const char *path, int flags, ...)
{
    opened++;
    event('O');
    violations += strcmp(path, "/dev/spidev3.0") != 0 ||
                  flags != (O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY);
    if (is("open-error")) {
        errno = EACCES;
        return -1;
    }
    return 71;
}
int __wrap_fstat(int fd, struct stat *st)
{
    stated++;
    event('S');
    violations += fd != 71 || opened != 1;
    if (is("stat-error") || is("stat-and-close-error")) {
        errno = EIO;
        return -1;
    }
    memset(st, 0, sizeof(*st));
    st->st_mode = S_IFCHR | 0600;
    st->st_rdev = makedev(153, is("dynamic-minor") ? 247 : 0);
    if (is("ordinary-file")) {
        st->st_mode = S_IFREG | 0600;
    }
    if (is("wrong-major")) {
        st->st_rdev = makedev(152, 0);
    }
    return 0;
}
int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list arguments;
    va_start(arguments, request);
    void *argument = va_arg(arguments, void *);
    va_end(arguments);
    if (fd != 71 || !argument || stated != 1 || closed) {
        violations++;
        errno = EPROTO;
        return -1;
    }
    if (request == SPI_IOC_MESSAGE(1)) {
        messages++;
        event((char)('0' + messages));
        if (configs != 4 || messages > 3) {
            violations++;
            errno = EPROTO;
            return -1;
        }
        struct spi_ioc_transfer *transfer = argument;
        struct spi_ioc_transfer expected = {0};
        expected.tx_buf = transfer->tx_buf;
        expected.rx_buf = transfer->rx_buf;
        expected.len = 4;
        expected.speed_hz = 100000;
        expected.bits_per_word = 8;
        if (sizeof(*transfer) != 32 || memcmp(transfer, &expected, sizeof(expected)) ||
            !transfer->tx_buf || !transfer->rx_buf || transfer->tx_buf == transfer->rx_buf) {
            violations++;
            errno = EPROTO;
            return -1;
        }
        const unsigned char *tx = (void *)(uintptr_t)transfer->tx_buf;
        unsigned char *rx = (void *)(uintptr_t)transfer->rx_buf;
        const unsigned char expected_tx[4] = {0x7d, (unsigned char)(0xfc + messages), 0x7f, 0x7f};
        const unsigned char zero[4] = {0};
        if (memcmp(tx, expected_tx, 4) || memcmp(rx, zero, 4)) {
            violations++;
            errno = EPROTO;
            return -1;
        }
        char failure[40];
        snprintf(failure, sizeof(failure), "ioctl-error-%d", messages);
        if (is(failure) || is("ioctl-interrupted") || is("ioctl-and-close-error")) {
            errno = is("ioctl-interrupted") ? EINTR : EREMOTEIO;
            return -1;
        }
        rx[0] = 0xa0;
        rx[1] = 0xb1;
        rx[2] = 0xc2;
        rx[3] = messages == 1 ? 0x50 : messages == 2 ? 0x5d : 0x83;
        if ((is("wrong-product") || is("wrong-id-and-close-error")) && messages == 1) {
            rx[3] = 0x51;
        }
        if (is("wrong-manufacturer") && messages == 2) {
            rx[3] = 0x5e;
        }
        if (is("revision-other") && messages == 3) {
            rx[3] = 0x42;
        }
        if (is("revision-zero") && messages == 3) {
            rx[3] = 0;
        }
        if (messages == 1 && strncmp(scenario, "short-", 6) == 0 &&
            scenario[6] >= '0' && scenario[6] <= '9') {
            return atoi(scenario + 6);
        }
        if (is("short-second") && messages == 2) {
            return 3;
        }
        if (is("short-third") && messages == 3) {
            return 3;
        }
        return 4;
    }
    static const unsigned long expected_requests[4] = {
        SPI_IOC_RD_MODE, SPI_IOC_RD_BITS_PER_WORD,
        SPI_IOC_RD_MAX_SPEED_HZ, SPI_IOC_RD_LSB_FIRST
    };
    static const char events[4] = {'M', 'B', 'H', 'L'};
    if (configs >= 4 || messages || request != expected_requests[configs]) {
        violations++;
        errno = EPROTO;
        return -1;
    }
    event(events[configs]);
    configs++;
    char failure[40];
    snprintf(failure, sizeof(failure), "config-error-%d", configs);
    if (is(failure)) {
        errno = EIO;
        return -1;
    }
    if (configs == 1) {
        *(uint8_t *)argument = is("mode-zero") ? 0 : is("mode-extra") ? 0x43 : 3;
    } else if (configs == 2) {
        *(uint8_t *)argument = is("bits-seven") ? 7 : 8;
    } else if (configs == 3) {
        *(uint32_t *)argument = is("speed-wrong") ? 100001 : is("speed-zero") ? 0 : 100000;
    } else {
        *(uint8_t *)argument = is("lsb-first") ? 1 : 0;
    }
    return 0;
}
int __wrap_close(int fd)
{
    closed++;
    event('C');
    violations += fd != 71 || closed != 1;
    if (is("close-error") || is("ioctl-and-close-error") ||
        is("stat-and-close-error") || is("wrong-id-and-close-error")) {
        errno = EIO;
        return -1;
    }
    return 0;
}
int __wrap_printf(const char *format, ...)
{
    char text[256];
    va_list arguments;
    va_start(arguments, format);
    int result = vsnprintf(text, sizeof(text), format, arguments);
    va_end(arguments);
    reports++;
    event('V');
    unsigned int revision = is("revision-other") ? 0x42 : is("revision-zero") ? 0 : 0x83;
    char expected[256];
    snprintf(expected, sizeof(expected),
             "CAP1188_IDENT product=0x50 manufacturer=0x5d revision=0x%02x\n", revision);
    violations += closed != 1 || is("close-error") || strcmp(text, expected) != 0;
    fputs(text, stdout);
    return result;
}
int __wrap_puts(const char *text)
{
    markers++;
    event('K');
    violations += closed != 1 || reports != 1 || is("close-error") ||
                  strcmp(text, "CAP1188_IDENTITY_VERIFIED") != 0;
    return __real_puts(text);
}
int main(int argc, char **argv)
{
    scenario = getenv("CAP1188_SCENARIO");
    if (!scenario) {
        scenario = "success";
    }
    int status = inspect_main(argc, argv);
    fprintf(stderr, "WRAP opened=%d stated=%d configs=%d messages=%d closed=%d reports=%d markers=%d violations=%d sequence=%s\n",
            opened, stated, configs, messages, closed, reports, markers, violations, sequence);
    return status;
}
'''
WRONG_BASELINE = r'''
#define _GNU_SOURCE
#include <fcntl.h>
#include <linux/spi/spidev.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--inspect")) {
        return 2;
    }
    int fd = open("/dev/spidev3.0", O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY);
    if (fd < 0) {
        return 2;
    }
    struct stat st;
    uint8_t mode, bits, lsb;
    uint32_t speed;
    if (fstat(fd, &st) || ioctl(fd, SPI_IOC_RD_MODE, &mode) ||
        ioctl(fd, SPI_IOC_RD_BITS_PER_WORD, &bits) ||
        ioctl(fd, SPI_IOC_RD_MAX_SPEED_HZ, &speed) ||
        ioctl(fd, SPI_IOC_RD_LSB_FIRST, &lsb)) {
        close(fd);
        return 2;
    }
    uint8_t values[3] = {0};
    for (unsigned int index = 0; index < 3; index++) {
        /* Deliberately wrong read framing: the fourth byte is a WRITE command. */
        uint8_t tx[4] = {0x7d, (uint8_t)(0xfd + index), 0x7f, 0x7e};
        uint8_t rx[4] = {0};
        struct spi_ioc_transfer transfer = {0};
        transfer.tx_buf = (uintptr_t)tx;
        transfer.rx_buf = (uintptr_t)rx;
        transfer.len = 4;
        transfer.speed_hz = 100000;
        transfer.bits_per_word = 8;
        if (ioctl(fd, SPI_IOC_MESSAGE(1), &transfer) != 4) {
            close(fd);
            return 2;
        }
        values[index] = rx[3];
    }
    if (close(fd)) {
        return 2;
    }
    printf("CAP1188_IDENT product=0x%02x manufacturer=0x%02x revision=0x%02x\n",
           values[0], values[1], values[2]);
    puts("CAP1188_IDENTITY_VERIFIED");
    return 0;
}
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh_directory(path):
    if path.exists() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Refuse existing or symlink evidence directory")
    if not path.resolve().is_relative_to((HERE / "build").resolve()):
        raise ValueError("Evidence directory escapes build")
    path.mkdir(parents=True)


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--wrong-baseline", action="store_true")
    parser.add_argument("--aarch64-qemu", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    output = HERE / "build" / ("inspect-tests-" + args.label)
    fresh_directory(output)
    wrappers = output / "wrappers.c"
    wrappers.write_text(WRAPPERS)
    source = SOURCE
    if args.wrong_baseline:
        source = output / "wrong-write-command-baseline.c"
        source.write_text(WRONG_BASELINE)
    compiler = "aarch64-linux-gnu-gcc" if args.aarch64_qemu else "gcc"
    object_file = output / "inspect.o"
    compile_argv = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Dmain=inspect_main",
                    "-c", str(source), "-o", str(object_file)]
    compiled = run(compile_argv)
    (output / "compile.txt").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise ValueError("Actual main failed to compile")
    executable = output / "wrapped-inspect"
    link_argv = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(wrappers), str(object_file),
                 "-Wl,--wrap=open", "-Wl,--wrap=fstat", "-Wl,--wrap=ioctl", "-Wl,--wrap=close",
                 "-Wl,--wrap=printf", "-Wl,--wrap=puts", "-o", str(executable)]
    if args.aarch64_qemu:
        link_argv.insert(1, "-static")
    linked = run(link_argv)
    (output / "link.txt").write_text(linked.stdout + linked.stderr)
    if linked.returncode:
        raise ValueError("Wrapped tool failed to link")
    prefix = [str(QEMU)] if args.aarch64_qemu else []
    scenarios = [
        ("success", 0, "OSMBHL123CVK"), ("dynamic-minor", 0, "OSMBHL123CVK"),
        ("revision-other", 0, "OSMBHL123CVK"), ("revision-zero", 0, "OSMBHL123CVK"),
        ("open-error", 2, "O"), ("stat-error", 2, "OSC"),
        ("ordinary-file", 2, "OSC"), ("wrong-major", 2, "OSC"),
        ("config-error-1", 2, "OSMC"), ("config-error-2", 2, "OSMBC"),
        ("config-error-3", 2, "OSMBHC"), ("config-error-4", 2, "OSMBHLC"),
        ("mode-zero", 2, "OSMC"), ("mode-extra", 2, "OSMC"),
        ("bits-seven", 2, "OSMBC"), ("speed-wrong", 2, "OSMBHC"),
        ("speed-zero", 2, "OSMBHC"), ("lsb-first", 2, "OSMBHLC"),
        ("ioctl-error-1", 2, "OSMBHL1C"), ("ioctl-error-2", 2, "OSMBHL12C"),
        ("ioctl-error-3", 2, "OSMBHL123C"), ("ioctl-interrupted", 2, "OSMBHL1C"),
        ("short-0", 2, "OSMBHL1C"), ("short-1", 2, "OSMBHL1C"),
        ("short-2", 2, "OSMBHL1C"), ("short-3", 2, "OSMBHL1C"),
        ("short-5", 2, "OSMBHL1C"), ("short-second", 2, "OSMBHL12C"),
        ("short-third", 2, "OSMBHL123C"),
        ("wrong-product", 1, "OSMBHL123C"), ("wrong-manufacturer", 1, "OSMBHL123C"),
        ("close-error", 2, "OSMBHL123C"), ("ioctl-and-close-error", 2, "OSMBHL1C"),
        ("stat-and-close-error", 2, "OSC"), ("wrong-id-and-close-error", 2, "OSMBHL123C")
    ]
    cases = []
    for scenario, expected_status, sequence in scenarios:
        environment = dict(os.environ, CAP1188_SCENARIO=scenario)
        result = subprocess.run([*prefix, str(executable), "--inspect"], env=environment,
                                capture_output=True, text=True, timeout=5)
        revision = "42" if scenario == "revision-other" else "00" if scenario == "revision-zero" else "83"
        expected_stdout = ("CAP1188_IDENT product=0x50 manufacturer=0x5d revision=0x" + revision +
                           "\nCAP1188_IDENTITY_VERIFIED\n") if expected_status == 0 else ""
        diagnostics = result.stderr.split("WRAP ", 1)[0]
        passed = (result.returncode == expected_status and result.stdout == expected_stdout and
                  "violations=0 sequence=" + sequence + "\n" in result.stderr and
                  (expected_status == 0 or bool(diagnostics.strip())))
        cases.append({"name": scenario, "passed": passed, "exit_code": result.returncode,
                      "expected_exit_code": expected_status, "expected_sequence": sequence,
                      "stdout": result.stdout, "stderr": result.stderr})
    for arguments in [[], ["--help"], ["--inspect", "/dev/spidev3.0"], ["--inspect", "0x00"],
                      ["--inspect", "--inspect"], ["--reset"], ["--write"]]:
        result = subprocess.run([*prefix, str(executable), *arguments], capture_output=True,
                                text=True, timeout=5)
        passed = (result.returncode == 2 and not result.stdout and "usage:" in result.stderr and
                  "violations=0 sequence=\n" in result.stderr)
        cases.append({"name": "reject-arguments-" + repr(arguments), "passed": passed,
                      "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    record = {"source_sha256": sha(source), "test_script_sha256": sha(Path(__file__)),
              "wrapper_sha256": sha(wrappers), "compile_argv": compile_argv, "link_argv": link_argv,
              "negative_control": args.wrong_baseline, "negative_control_defect": "fourth byte WRITE 0x7e instead of READ 0x7f" if args.wrong_baseline else None,
              "target": "AArch64 QEMU user with wrapped device calls" if args.aarch64_qemu else "host x86_64 wrapped device calls",
              "cases": cases, "failures": sum(not case["passed"] for case in cases),
              "executable_sha256": sha(executable), "board_tested": False, "real_spi_access": False,
              "device_syscalls_wrapped": ["open", "fstat", "ioctl", "close"],
              "qemu_sha256": sha(QEMU) if args.aarch64_qemu else None}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    for case in cases:
        print(case["name"] + " " + ("PASS" if case["passed"] else "FAIL"))
    print("TOTAL_FAILURES=" + str(record["failures"]))
    raise SystemExit(int(record["failures"] != 0))


if __name__ == "__main__":
    main()
