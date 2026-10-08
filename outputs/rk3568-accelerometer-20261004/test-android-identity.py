#!/usr/bin/env python3
"""Run the real tool with wrapped device syscalls; never open a real I2C bus."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "android-identity.c"
WRAPPERS = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

extern int identity_main(int argc, char **argv);
extern int __real_puts(const char *s);
static const char *scenario;
static int opened, stated, transferred, closed, markers, violations;
static char sequence[64];
static void event(char c)
{
    size_t length = strlen(sequence);
    sequence[length] = c;
    sequence[length + 1] = 0;
}
int __wrap_open(const char *path, int flags, ...)
{
    opened++;
    event('O');
    if (strcmp(path, "/dev/i2c-5") != 0 ||
        flags != (O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY)) {
        violations++;
    }
    if (strcmp(scenario, "open-error") == 0) {
        errno = EACCES;
        return -1;
    }
    return 71;
}
int __wrap_fstat(int fd, struct stat *st)
{
    stated++;
    event('S');
    violations += fd != 71;
    if (strcmp(scenario, "stat-error") == 0) {
        errno = EIO;
        return -1;
    }
    memset(st, 0, sizeof(*st));
    st->st_mode = S_IFCHR | 0600;
    st->st_rdev = makedev(89, 5);
    if (strcmp(scenario, "ordinary-file") == 0) {
        st->st_mode = S_IFREG | 0600;
    }
    if (strcmp(scenario, "wrong-major") == 0) {
        st->st_rdev = makedev(90, 5);
    }
    if (strcmp(scenario, "wrong-minor") == 0) {
        st->st_rdev = makedev(89, 4);
    }
    return 0;
}
static uint16_t u16(const unsigned char *p)
{
    uint16_t value;
    memcpy(&value, p, sizeof(value));
    return value;
}
static uint32_t u32(const unsigned char *p)
{
    uint32_t value;
    memcpy(&value, p, sizeof(value));
    return value;
}
static uint64_t u64(const unsigned char *p)
{
    uint64_t value;
    memcpy(&value, p, sizeof(value));
    return value;
}
int __wrap_ioctl(int fd, unsigned long request, ...)
{
    transferred++;
    event('I');
    va_list arguments;
    va_start(arguments, request);
    const unsigned char *outer = va_arg(arguments, const unsigned char *);
    va_end(arguments);
    if (fd != 71 || request != 0x0707 || !outer ||
        u32(outer + 8) != 2 || u32(outer + 12) != 0) {
        violations++;
        errno = EPROTO;
        return -1;
    }
    const unsigned char *messages = (void *)(uintptr_t)u64(outer);
    /* Check the first message's trailing eight bytes before inspecting message 1.
       A native 16-byte layout puts its nonzero second message fields here. */
    if (!messages || u16(messages) != 0x15 || u16(messages + 2) != 0 ||
        u16(messages + 4) != 1 || u16(messages + 6) != 0 || u64(messages + 16) != 0) {
        violations++;
        errno = EPROTO;
        return -1;
    }
    const unsigned char *second = messages + 24;
    if (u16(second) != 0x15 || u16(second + 2) != 1 || u16(second + 4) != 1 ||
        u16(second + 6) != 0 || u64(second + 16) != 0 ||
        u64(messages + 8) == 0 || u64(second + 8) == 0 ||
        *(unsigned char *)(uintptr_t)u64(messages + 8) != 0x0f) {
        violations++;
        errno = EPROTO;
        return -1;
    }
    if (strcmp(scenario, "ioctl-error") == 0) {
        errno = EREMOTEIO;
        return -1;
    }
    if (strcmp(scenario, "ioctl-interrupted") == 0) {
        errno = EINTR;
        return -1;
    }
    *(unsigned char *)(uintptr_t)u64(second + 8) = strcmp(scenario, "wrong-id") == 0 ? 4 : 5;
    if (strcmp(scenario, "short-zero") == 0) {
        return 0;
    }
    if (strcmp(scenario, "short-one") == 0) {
        return 1;
    }
    if (strcmp(scenario, "unexpected-three") == 0) {
        return 3;
    }
    return 2;
}
int __wrap_close(int fd)
{
    closed++;
    event('C');
    violations += fd != 71;
    if (strcmp(scenario, "close-error") == 0) {
        errno = EIO;
        return -1;
    }
    return 0;
}
int __wrap_puts(const char *s)
{
    markers++;
    event('M');
    violations += closed != 1 || strcmp(scenario, "close-error") == 0 ||
                  strcmp(s, "ANDROID_LEGACY24_IDENTITY_OK=0x05") != 0;
    return __real_puts(s);
}
int main(int argc, char **argv)
{
    scenario = getenv("IDENTITY_SCENARIO");
    if (!scenario) {
        scenario = "success";
    }
    int status = identity_main(argc, argv);
    fprintf(stderr, "WRAP opened=%d stated=%d transferred=%d closed=%d markers=%d violations=%d sequence=%s\n",
            opened, stated, transferred, closed, markers, violations, sequence);
    return status;
}
'''
WRONG_BASELINE = r'''
#define _GNU_SOURCE
#include <fcntl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--android-legacy24") != 0) {
        return 2;
    }
    int fd = open("/dev/i2c-5", O_RDWR | O_CLOEXEC | O_NOFOLLOW | O_NOCTTY);
    if (fd < 0) {
        return 2;
    }
    struct stat st;
    if (fstat(fd, &st)) {
        close(fd);
        return 2;
    }
    unsigned char index = 0x0f, identity = 0;
    /* Negative control: normal Linux native16 ABI, deliberately wrong for this Image. */
    struct i2c_msg messages[2] = {{.addr = 0x15, .len = 1, .buf = &index},
                                 {.addr = 0x15, .flags = I2C_M_RD, .len = 1, .buf = &identity}};
    struct i2c_rdwr_ioctl_data data = {.msgs = messages, .nmsgs = 2};
    int status = ioctl(fd, I2C_RDWR, &data);
    close(fd);
    if (status != 2) {
        return 2;
    }
    puts("ANDROID_LEGACY24_IDENTITY_OK=0x05");
    return 0;
}
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--wrong-baseline", action="store_true")
    parser.add_argument("--aarch64-qemu", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    output = HERE / "build" / ("android-identity-tests-" + args.label)
    if output.exists() or output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Refuse existing or symlink evidence")
    output.mkdir(parents=True)
    wrappers = output / "wrappers.c"
    wrappers.write_text(WRAPPERS)
    source = SOURCE
    if args.wrong_baseline:
        source = output / "wrong-native16-baseline.c"
        source.write_text(WRONG_BASELINE)
    object_file = output / "identity.o"
    compiler = "aarch64-linux-gnu-gcc" if args.aarch64_qemu else "gcc"
    compile_argv = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Dmain=identity_main",
                    "-c", str(source), "-o", str(object_file)]
    compiled = subprocess.run(compile_argv, capture_output=True, text=True)
    (output / "compile.txt").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise ValueError("Real wrapper compile failed")
    executable = output / "wrapped-identity"
    link_argv = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(wrappers), str(object_file),
                 "-Wl,--wrap=open", "-Wl,--wrap=fstat", "-Wl,--wrap=ioctl", "-Wl,--wrap=close",
                 "-Wl,--wrap=puts", "-o", str(executable)]
    if args.aarch64_qemu:
        link_argv.insert(1, "-static")
    linked = subprocess.run(link_argv, capture_output=True, text=True)
    (output / "link.txt").write_text(linked.stdout + linked.stderr)
    if linked.returncode:
        raise ValueError("Real wrapper link failed")
    import os
    prefix = [str(ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static")] if args.aarch64_qemu else []
    cases = []
    scenarios = [("success", 0, "OSICM"), ("open-error", 2, "O"), ("stat-error", 2, "OSC"),
                 ("ordinary-file", 2, "OSC"), ("wrong-major", 2, "OSC"), ("wrong-minor", 2, "OSC"),
                 ("ioctl-error", 2, "OSIC"), ("ioctl-interrupted", 2, "OSIC"),
                 ("short-zero", 2, "OSIC"), ("short-one", 2, "OSIC"), ("unexpected-three", 2, "OSIC"),
                 ("wrong-id", 1, "OSIC"), ("close-error", 2, "OSIC")]
    for scenario, expected_status, sequence in scenarios:
        environment = dict(os.environ, IDENTITY_SCENARIO=scenario)
        result = subprocess.run([*prefix, str(executable), "--android-legacy24"], env=environment,
                                capture_output=True, text=True, timeout=5)
        expected_marker = "ANDROID_LEGACY24_IDENTITY_OK=0x05\n" if expected_status == 0 else ""
        passed = (result.returncode == expected_status and result.stdout == expected_marker and
                  "violations=0 sequence=" + sequence + "\n" in result.stderr)
        cases.append({"name": scenario, "passed": passed, "exit_code": result.returncode,
                      "expected_exit_code": expected_status, "expected_sequence": sequence,
                      "stdout": result.stdout, "stderr": result.stderr})
    for arguments in [[], ["--help"], ["--linux"], ["--android-legacy24", "/dev/i2c-5"],
                      ["--android-legacy24", "--android-legacy24"]]:
        result = subprocess.run([*prefix, str(executable), *arguments], capture_output=True, text=True, timeout=5)
        passed = result.returncode == 2 and result.stdout == "" and "violations=0 sequence=\n" in result.stderr
        cases.append({"name": "reject-arguments-" + repr(arguments), "passed": passed,
                      "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    record = {"source_sha256": sha(source), "test_script_sha256": sha(Path(__file__)),
              "wrapper_sha256": sha(wrappers), "compile_argv": compile_argv, "link_argv": link_argv,
              "negative_control": args.wrong_baseline, "cases": cases,
              "target": "AArch64 QEMU user with wrapped device calls" if args.aarch64_qemu else "host x86_64 wrapped device calls",
              "failures": sum(not case["passed"] for case in cases), "board_tested": False,
              "device_syscalls_wrapped": ["open", "fstat", "ioctl", "close"], "real_i2c_access": False}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    for case in cases:
        print(case["name"] + " " + ("PASS" if case["passed"] else "FAIL"))
    print("TOTAL_FAILURES=" + str(record["failures"]))
    raise SystemExit(int(record["failures"] != 0))


if __name__ == "__main__":
    main()
