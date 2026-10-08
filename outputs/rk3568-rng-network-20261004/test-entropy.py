#!/usr/bin/env python3
"""Check the real program against one-shot syscall failures and host/QEMU execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"

STUB = r'''#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>

static unsigned int calls;

ssize_t __wrap_getrandom(void *buffer, size_t length, unsigned int flags) {
    const char *mode = getenv("ENTROPY_STUB_CASE");
    calls++;
    if (buffer == NULL || length != 1 || flags != GRND_NONBLOCK) {
        fputs("WRONG_GETRANDOM_CONTRACT\n", stderr);
        errno = EINVAL;
        return -1;
    }
    if (strcmp(mode, "ready") == 0) {
        ((unsigned char *)buffer)[0] = 0xa7;
        return 1;
    }
    if (strcmp(mode, "short") == 0) {
        return 0;
    }
    if (strcmp(mode, "oversize") == 0) {
        return 2;
    }
    if (strcmp(mode, "eagain") == 0) {
        errno = EAGAIN;
    } else if (strcmp(mode, "eintr") == 0) {
        errno = EINTR;
    } else if (strcmp(mode, "eio") == 0) {
        errno = EIO;
    } else {
        errno = EINVAL;
    }
    return -1;
}

__attribute__((destructor)) static void report_calls(void) {
    fprintf(stderr, "GETRANDOM_CALLS=%u\n", calls);
}
'''

WRONG_BASELINE = r'''#include <stdio.h>
#include <sys/random.h>

int main(void) {
    unsigned char byte;
    ssize_t length = getrandom(&byte, 1, GRND_NONBLOCK);
    (void)length;
    puts("CRNG_READY");
    return 0;
}
'''


def new_directory(revision):
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", revision):
        raise ValueError("Need a red-vN or green-vN evidence revision")
    build = HERE / "build/entropy"
    current = HERE
    for part in build.relative_to(HERE).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink build component")
    build.mkdir(parents=True, exist_ok=True)
    output = build / revision
    if os.path.lexists(output):
        raise ValueError("Refusing existing test evidence: " + str(output))
    output.mkdir()
    return output


def invoke(argv, mode=None):
    environment = dict(os.environ)
    if mode is not None:
        environment["ENTROPY_STUB_CASE"] = mode
    return subprocess.run(argv, capture_output=True, text=True, env=environment, timeout=10)


def check_case(binary, mode, args, code, message, count):
    result = invoke([str(binary)] + args, mode)
    assert result.returncode == code, (mode, args, result.returncode, result.stdout, result.stderr)
    assert result.stdout == message, (mode, args, result.stdout)
    assert result.stderr.count("GETRANDOM_CALLS=" + str(count) + "\n") == 1, result.stderr
    assert "WRONG_GETRANDOM_CONTRACT" not in result.stderr, result.stderr
    if count == 0:
        assert "Usage: entropy-check [--check]" in result.stderr, result.stderr
    else:
        assert result.stderr == "GETRANDOM_CALLS=" + str(count) + "\n", result.stderr
    return {"case": mode, "arguments": args, "exit_code": code,
            "stdout": result.stdout.strip(), "syscall_count": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red-baseline", action="store_true")
    parser.add_argument("--revision")
    parser.add_argument("--binary", type=Path, default=HERE / "entropy-check")
    args = parser.parse_args()
    output = new_directory(args.revision or ("red-v1" if args.red_baseline else "green-v1"))
    stub = output / "getrandom-stub.c"
    stub.write_text(STUB)
    source = HERE / "entropy-check.c"
    if args.red_baseline:
        source = output / "wrong-baseline.c"
        source.write_text(WRONG_BASELINE)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Need ordinary source file")
    wrapped = output / "entropy-wrapped-native"
    compile_command = ["gcc", "-O2", "-Wall", "-Wextra", "-Werror", str(source), str(stub),
                       "-Wl,--wrap=getrandom", "-o", str(wrapped)]
    subprocess.run(compile_command, capture_output=True, check=True)
    if args.red_baseline:
        result = invoke([str(wrapped)], "eagain")
        rejected = result.returncode != 1 or result.stdout != "CRNG_NOT_READY\n"
        evidence = {"status": "EXPECTED_RED_FAILURE" if rejected else "RED_DID_NOT_FAIL",
                    "case": "EAGAIN must not report CRNG_READY", "expected_exit": 1,
                    "expected_stdout": "CRNG_NOT_READY", "actual_exit": result.returncode,
                    "actual_stdout": result.stdout.strip(), "actual_stderr": result.stderr.strip(),
                    "compile_argv": compile_command, "board_tested": False}
        (output / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence, indent=2))
        return 1 if rejected else 2
    cases = [
        ("ready", [], 0, "CRNG_READY\n", 1),
        ("ready", ["--check"], 0, "CRNG_READY\n", 1),
        ("eagain", [], 1, "CRNG_NOT_READY\n", 1),
        ("eintr", [], 2, "CRNG_CHECK_FAILED\n", 1),
        ("eio", [], 2, "CRNG_CHECK_FAILED\n", 1),
        ("invalid-flags", [], 2, "CRNG_CHECK_FAILED\n", 1),
        ("short", [], 2, "CRNG_CHECK_FAILED\n", 1),
        ("oversize", [], 2, "CRNG_CHECK_FAILED\n", 1),
        ("ready", ["--bad-flag"], 2, "", 0),
        ("ready", ["--check", "extra"], 2, "", 0),
    ]
    passed = [check_case(wrapped, *case) for case in cases]
    native = output / "entropy-native"
    native_command = ["gcc", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(native)]
    subprocess.run(native_command, capture_output=True, check=True)
    real_host = invoke([str(native), "--check"])
    assert real_host.returncode == 0 and real_host.stdout == "CRNG_READY\n" and not real_host.stderr, real_host
    binary = args.binary.resolve(strict=True)
    assert binary.is_relative_to(HERE) and binary.is_file() and not args.binary.is_symlink()
    real_qemu = invoke([str(QEMU), str(binary), "--check"])
    assert real_qemu.returncode == 0 and real_qemu.stdout == "CRNG_READY\n" and not real_qemu.stderr, real_qemu
    invalid_qemu = invoke([str(QEMU), str(binary), "--bad-flag"])
    assert invalid_qemu.returncode == 2 and not invalid_qemu.stdout
    assert "Usage: entropy-check [--check]" in invalid_qemu.stderr
    summary = {
        "status": "ENTROPY_HOST_TESTS_PASSED", "stub_checks": len(passed), "cases": passed,
        "real_host_syscall": {"exit_code": real_host.returncode, "stdout": real_host.stdout.strip()},
        "qemu_static_binary": {"exit_code": real_qemu.returncode, "stdout": real_qemu.stdout.strip()},
        "qemu_invalid_arguments_exit": invalid_qemu.returncode,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "compile_argv": [compile_command, native_command], "board_tested": False,
        "source_linux_trng_binding_tested": False,
    }
    (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
