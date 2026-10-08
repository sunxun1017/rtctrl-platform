#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the fixed CAP1188 identity tool offline, without accessing SPI devices."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / "cap1188-inspect.c"
TEST = HERE / "test-cap1188-inspect.py"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
KERNEL_UAPI = ROOT / "third_party/linux-rk3588/include/uapi/linux/spi/spidev.h"
CROSS_UAPI = Path("/usr/aarch64-linux-gnu/include/linux/spi/spidev.h")
EXPECTED_COMPILER = "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain_input(path):
    if not path.is_file() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Refuse missing or symlink input: " + str(path))


def new_directory(path):
    if path.exists() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Refuse existing or symlink output")
    if not path.resolve().is_relative_to((HERE / "build").resolve()):
        raise ValueError("Output escapes build directory")


def command(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def validated_tests():
    evidence = {}
    for label in ["red-v2", "green-v3", "green-v4"]:
        directory = HERE / "build" / ("inspect-tests-" + label)
        record_path = directory / "result.json"
        plain_input(record_path)
        record = json.loads(record_path.read_text())
        if record["test_script_sha256"] != sha(TEST):
            raise ValueError("Test evidence uses a different test script")
        if record["wrapper_sha256"] != sha(directory / "wrappers.c"):
            raise ValueError("Wrapper evidence changed")
        if record["executable_sha256"] != sha(directory / "wrapped-inspect"):
            raise ValueError("Test executable changed")
        if record["board_tested"] or record["real_spi_access"]:
            raise ValueError("Offline wrapped tests required")
        if record["failures"] != sum(not case["passed"] for case in record["cases"]):
            raise ValueError("Test result counters disagree")
        if label.startswith("green"):
            if record["negative_control"] or record["failures"] or record["source_sha256"] != sha(SOURCE):
                raise ValueError("Current source must pass all wrapper tests")
            if len(record["cases"]) != 42:
                raise ValueError("Incomplete current failure test suite")
        else:
            control = directory / "wrong-write-command-baseline.c"
            success_case = next(case for case in record["cases"] if case["name"] == "success")
            if (not record["negative_control"] or not record["failures"] or
                record["source_sha256"] != sha(control) or success_case["passed"] or
                "violations=1 sequence=OSMBHL1C" not in success_case["stderr"]):
                raise ValueError("Compiled wrong-frame negative control must actually fail")
        if label == "green-v4" and (record["target"] != "AArch64 QEMU user with wrapped device calls" or
                                     record["qemu_sha256"] != sha(QEMU)):
            raise ValueError("Matching AArch64 QEMU evidence required")
        evidence[label] = {"result_sha256": sha(record_path), "source_sha256": record["source_sha256"],
                           "cases": len(record["cases"]), "failures": record["failures"],
                           "target": record["target"], "negative_control": record["negative_control"]}
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / "build" / ("inspect-" + args.version)
    new_directory(output)
    for path in [SOURCE, TEST, QEMU, KERNEL_UAPI, CROSS_UAPI]:
        plain_input(path)
    tests = validated_tests()
    compiler_result = command(["aarch64-linux-gnu-gcc", "--version"])
    if compiler_result.returncode or compiler_result.stdout.splitlines()[0] != EXPECTED_COMPILER:
        raise ValueError("Expected locked cross compiler unavailable")
    output.mkdir(parents=True)
    binary = output / "cap1188-inspect"
    compile_argv = ["aarch64-linux-gnu-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-static", "-fno-ident", "-Wl,--build-id=none", str(SOURCE), "-o", str(binary)]
    built = command(compile_argv)
    (output / "build.txt").write_text(built.stdout + built.stderr)
    if built.returncode:
        raise ValueError("Static CAP1188 tool build failed")
    data = binary.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (2, 183):
        raise ValueError("Expected ELF64 LE AArch64 executable")
    readelf = command(["aarch64-linux-gnu-readelf", "-h", "-l", "-d", str(binary)])
    (output / "readelf.txt").write_text(readelf.stdout + readelf.stderr)
    if readelf.returncode or "INTERP" in readelf.stdout or "NEEDED" in readelf.stdout:
        raise ValueError("Dynamic executable refused")
    qemu_cases = []
    # The final unwrapped executable only rejects arguments here. Successful device
    # reads and failures are covered by wrapped AArch64 tests, never a host SPI bus.
    for arguments in [[], ["--help"], ["--inspect", "/dev/spidev3.0"], ["--write"]]:
        result = command([str(QEMU), str(binary), *arguments])
        if result.returncode != 2 or result.stdout or "usage:" not in result.stderr:
            raise ValueError("Final executable argument rejection failed")
        qemu_cases.append({"arguments": arguments, "exit_code": result.returncode,
                           "stdout": result.stdout, "stderr": result.stderr})
    boundaries = []
    for version, expected_text in [(args.version, "Refuse existing or symlink output"),
                                   ("../outside", "version must be vN"),
                                   ("/tmp/inspect", "version must be vN")]:
        result = command([sys.executable, str(Path(__file__)), "--version", version])
        if result.returncode == 0 or expected_text not in result.stderr:
            raise ValueError("Actual builder output refusal failed")
        boundaries.append({"version": version, "exit_code": result.returncode,
                           "expected_diagnostic": expected_text, "stderr": result.stderr})
    manifest = {
        "license": "MIT", "source_sha256": sha(SOURCE), "test_script_sha256": sha(TEST),
        "builder_sha256": sha(Path(__file__)), "binary": "cap1188-inspect",
        "binary_bytes": len(data), "binary_sha256": sha(binary),
        "binary_crc32": format(zlib.crc32(data), "08x"),
        "compiler": EXPECTED_COMPILER, "compile_argv": compile_argv,
        "elf": "ELF64 LE AArch64 ET_EXEC", "no_interp": True, "no_needed": True,
        "uapi_sources": {"linux_5_10_spidev_header_sha256": sha(KERNEL_UAPI),
                          "cross_compiler_spidev_header_sha256": sha(CROSS_UAPI),
                          "transfer_bytes": 32, "transfer_offsets": {"tx_buf": 0, "rx_buf": 8,
                              "len": 16, "speed_hz": 20, "bits_per_word": 26, "cs_change": 27, "pad": 31}},
        "protocol_source": "Microchip CAP1188 DS00001620C Figure 4-7; primary-source review by parallel datasheet agent",
        "protocol": {"tx": ["0x7d", "register", "0x7f", "0x7f"], "valid_rx_byte": 3,
                     "continuous_cs_per_register": True, "transfer_count_per_message": 1,
                     "message_return_required_bytes": 4, "speed_hz": 100000,
                     "bits_per_word": 8, "cs_change": 0, "other_transfer_fields": "zero"},
        "operation": {"arguments": ["--inspect"], "path": "/dev/spidev3.0",
                      "character_major": 153, "minor": "dynamic; board runtime must verify sysfs/dev mapping",
                      "open_flags": ["O_RDWR", "O_CLOEXEC", "O_NOFOLLOW", "O_NOCTTY"],
                      "configuration_reads": ["SPI_IOC_RD_MODE", "SPI_IOC_RD_BITS_PER_WORD",
                                                "SPI_IOC_RD_MAX_SPEED_HZ", "SPI_IOC_RD_LSB_FIRST"],
                      "required_configuration": {"mode": 3, "bits_per_word": 8,
                                                 "max_speed_hz": 100000, "lsb_first": 0},
                      "identity_registers": {"0xfd": "product 0x50", "0xfe": "manufacturer 0x5d",
                                             "0xff": "revision recorded, any byte accepted"},
                      "successful_message_calls": 3, "maximum_message_calls": 3,
                      "configuration_write_ioctls": 0, "control_register_writes": 0,
                      "scan": False, "force": False, "reset": False, "retries": 0},
        "stdout_on_success": "CAP1188_IDENT product=0x50 manufacturer=0x5d revision=0xNN\nCAP1188_IDENTITY_VERIFIED\n",
        "success_only_after_close": True, "exit_codes": {"verified": 0, "identity_mismatch": 1,
                                                            "arguments_or_system_error_or_short_transfer": 2},
        "tests": tests, "unwrapped_qemu_argument_cases": qemu_cases,
        "builder_refusal_tests": boundaries, "qemu_sha256": sha(QEMU),
        "board_tested": False, "real_spi_access_on_host": False,
        "limitations": ["Device open and SPI read transfers can affect hardware state",
                        "Wrapped tests prove ABI/frame/error flow, not physical timing or chip response",
                        "Identity reads do not validate touch channels, input events, initialization, or reset",
                        "Wrong identity or short/error transfer must stop before any initialization or control writes"]
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"binary": str(binary), "bytes": len(data), "sha256": sha(binary),
                      "crc32": manifest["binary_crc32"], "manifest": str(manifest_path),
                      "manifest_sha256": sha(manifest_path), "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
