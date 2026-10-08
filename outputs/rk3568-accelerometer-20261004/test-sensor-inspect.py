#!/usr/bin/env python3
"""Exercise the actual helper with linker-wrapped Linux I2C syscalls."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
WRAPPER = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
static int calls;
static const unsigned char regs[] = {0x0f, 0x0d, 0x0b};
static int mode(void) { return atoi(getenv("TEST_MODE")); }
int __wrap_open(const char *path, int flags, ...) {
    if (strcmp(path, "/dev/i2c-5") || flags != (O_RDONLY|O_CLOEXEC|O_NOFOLLOW)) _exit(90);
    if (mode() == 1) { errno = EACCES; return -1; }
    return 42;
}
int __wrap_fstat(int fd, struct stat *st) {
    if (fd != 42) _exit(91);
    memset(st, 0, sizeof(*st));
    st->st_mode = mode() == 2 ? S_IFREG : S_IFCHR;
    st->st_rdev = makedev(89, mode() == 3 ? 6 : 5);
    if (mode() == 4) { errno = EIO; return -1; }
    return 0;
}
int __wrap_ioctl(int fd, unsigned long request, ...) {
    va_list args;
    va_start(args, request);
    struct i2c_rdwr_ioctl_data *rdwr = va_arg(args, struct i2c_rdwr_ioctl_data *);
    va_end(args);
    if (fd != 42 || request != I2C_RDWR || rdwr->nmsgs != 2 || calls >= 3) _exit(92);
    struct i2c_msg *m = rdwr->msgs;
    if (m[0].addr != 0x15 || m[1].addr != 0x15 || m[0].flags != 0 ||
        m[1].flags != I2C_M_RD || m[0].len != 1 || m[1].len != 1 ||
        *m[0].buf != regs[calls]) _exit(93);
    ++calls;
    if (mode() == 5) { errno = ENXIO; return -1; }
    if (mode() == 6) return 1;
    if (mode() == 7) return 0;
    *m[1].buf = calls == 1 ? (mode() == 8 ? 0x04 : 0x05) :
        calls == 2 ? (mode() == 9 ? 0 : 1) : (mode() == 10 ? 1 : 0);
    return 2;
}
int __wrap_close(int fd) { if (fd != 42) _exit(94); return 0; }
'''


def main():
    source = HERE / "sensor-inspect.c"
    with tempfile.TemporaryDirectory(prefix="sensor-inspect-") as directory:
        work = Path(directory)
        wrapper = work / "wrapper.c"
        wrapper.write_text(WRAPPER)
        binary = work / "test"
        subprocess.run(["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                        str(source), str(wrapper), "-o", str(binary),
                        "-Wl,--wrap=open,--wrap=fstat,--wrap=ioctl,--wrap=close"], check=True)
        cases = [("normal identity", 0, [], 0), ("default off", 0, ["--require-off"], 0)]
        cases += [(name, mode, [], 1) for name, mode in [
            ("open failure", 1), ("regular file rejected", 2), ("wrong bus rejected", 3),
            ("fstat failure", 4), ("I2C negative", 5), ("short one", 6), ("short zero", 7)]]
        cases += [("wrong identity", 8, [], 3), ("enabled rejected", 9, ["--require-off"], 4),
                  ("interrupt enabled rejected", 10, ["--require-off"], 4),
                  ("unknown argument", 0, ["/dev/i2c-0"], 2)]
        passed = []
        for name, mode, args, status in cases:
            import os
            result = subprocess.run([str(binary), *args], env={**os.environ, "TEST_MODE": str(mode)},
                                    capture_output=True, text=True)
            if result.returncode != status:
                raise AssertionError(f"{name}: expected {status}, got {result.returncode}: {result.stdout} {result.stderr}")
            if status != 0 and "SENSOR_IDENTITY_READ_COMPLETE" in result.stdout:
                raise AssertionError("Failure printed success: " + name)
            passed.append(name)
    print(json.dumps({"status": "FIXED_ADDRESS_I2C_HELPER_TESTS_PASSED", "passed": passed,
                      "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
