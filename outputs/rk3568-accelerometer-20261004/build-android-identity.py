#!/usr/bin/env python3
"""Build the explicitly selected Android legacy24 identity-only tool offline."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "android-identity.c"
ANDROID_IMAGE = ROOT / "outputs/rk3568-mcu-baseline-20261003/private/original-Image.bin"
ANDROID_SHA = "54e75d6dbb03ab96ea938eb940fe64cab91f3f81a3e43a9e98d763980dd7779d"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv):
    return subprocess.run(argv, text=True, capture_output=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / "build" / ("android-identity-" + args.version)
    if output.exists() or output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Refuse existing or symlink output")
    if sha(ANDROID_IMAGE) != ANDROID_SHA:
        raise ValueError("Original Android Image fingerprint changed")
    tests = {}
    for label in ["red-v2", "green-v1", "green-v2"]:
        result_path = HERE / "build" / ("android-identity-tests-" + label) / "result.json"
        record = json.loads(result_path.read_text())
        if label.startswith("green") and (record["failures"] or record["source_sha256"] != sha(SOURCE)):
            raise ValueError("Current real source must pass wrapper tests first")
        if label.startswith("red") and (not record["negative_control"] or not record["failures"]):
            raise ValueError("Meaningful native16 negative control evidence required")
        tests[label] = {"result_sha256": sha(result_path), "failures": record["failures"],
                       "cases": len(record["cases"]), "target": record.get("target", "host x86_64 wrapped device calls")}
    compiler_result = command(["aarch64-linux-gnu-gcc", "--version"])
    if compiler_result.returncode:
        raise ValueError("Cross compiler unavailable")
    compiler = compiler_result.stdout.splitlines()[0]
    if compiler != "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0":
        raise ValueError("Unexpected cross compiler")
    output.mkdir(parents=True)
    binary = output / "android-identity"
    argv = ["aarch64-linux-gnu-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-static",
            "-fno-ident", "-Wl,--build-id=none", str(SOURCE), "-o", str(binary)]
    built = command(argv)
    (output / "build.txt").write_text(built.stdout + built.stderr)
    if built.returncode:
        raise ValueError("Static identity build failed")
    data = binary.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (2, 183):
        raise ValueError("Expected static ELF64 LE AArch64 executable")
    headers = command(["aarch64-linux-gnu-readelf", "-h", "-l", "-d", str(binary)])
    (output / "readelf.txt").write_text(headers.stdout + headers.stderr)
    if headers.returncode or "INTERP" in headers.stdout or "NEEDED" in headers.stdout:
        raise ValueError("Dynamic executable refused")
    qemu_cases = []
    # Only argument rejection is exercised on the final unwrapped binary.
    # Device access for all success/error scenarios is mocked in the AArch64 tests.
    for arguments in [[], ["--linux"], ["--android-legacy24", "/dev/i2c-5"]]:
        checked = command([str(QEMU), str(binary), *arguments])
        if checked.returncode != 2 or checked.stdout or "usage:" not in checked.stderr:
            raise ValueError("Final binary argument rejection failed")
        qemu_cases.append({"arguments": arguments, "exit_code": checked.returncode,
                           "stdout": checked.stdout, "stderr": checked.stderr})
    manifest = {"source_sha256": sha(SOURCE), "builder_sha256": sha(Path(__file__)),
                "binary": "android-identity", "binary_sha256": sha(binary), "binary_bytes": len(data),
                "binary_crc32": format(zlib.crc32(data), "08x"), "compiler": compiler, "compile_argv": argv,
                "elf": "ELF64 LE AArch64 ET_EXEC", "no_interp": True, "no_needed": True,
                "bound_android_image_sha256": ANDROID_SHA, "private_image_not_copied": True,
                "mode": "--android-legacy24 (explicit only; no automatic probe or fallback)",
                "abi_layout": {"outer_bytes": 16, "outer_fields": {"messages": 0, "count": 8, "zero_padding": 12},
                               "message_stride": 24, "message_fields": {"addr_u16": 0, "flags_u16": 2,
                                   "len_u16": 4, "zero_padding_u16": 6, "buffer_u64": 8, "zero_reserved_u64": 16}},
                "abi_audit_basis": "Parent offline disassembly of this exact Image and rk3x controller: trailing 8 bytes are opaque and are initialized to zero; not a generic Android ABI claim",
                "operation": {"path": "/dev/i2c-5", "character_major_minor": "89:5", "address": "0x15",
                              "register": "WHO_AM_I 0x0f", "messages": ["write index only, 1 byte", "read identity only, 1 byte"],
                              "ioctl": "I2C_RDWR 0x0707", "ioctl_calls": 1, "expected_identity": "0x05",
                              "control_register_value_writes": 0, "scan": False, "slave_force": False, "retries": 0},
                "success_marker": "ANDROID_LEGACY24_IDENTITY_OK=0x05 (only after successful close)",
                "tests": tests, "unwrapped_qemu_argument_cases": qemu_cases,
                "qemu_sha256": sha(QEMU), "board_tested": False, "real_i2c_access_on_host": False,
                "limitations": ["Hardware execution requires fresh confirmation of this original Image and rk3x controller",
                                "Wrapped syscall tests verify byte layout and failure flow, not physical sensor response",
                                "Identity read does not establish Linux driver operation or sensor sampling"]}
    manifest_path = output / "android-identity-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"binary": str(binary), "binary_bytes": len(data), "binary_sha256": sha(binary),
                      "crc32": manifest["binary_crc32"], "manifest": str(manifest_path),
                      "manifest_sha256": sha(manifest_path), "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
