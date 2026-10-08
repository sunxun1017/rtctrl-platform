#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build and audit a static AArch64 cached-control inspector, entirely offline."""
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
SOURCE = HERE / "alsa-inspect.c"
TEST = HERE / "test-alsa-inspect.py"
KERNEL = ROOT / "third_party/linux-rk3588"
LOCKED_UAPI = KERNEL / "include/uapi/sound/asound.h"
CROSS_UAPI = Path("/usr/aarch64-linux-gnu/include/sound/asound.h")
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
EXPECTED_HEAD = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
EXPECTED_LOCKED = "138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447"
EXPECTED_CROSS = "b62c8bff11f4aeea5df38899dbb2e18af10c0ffba770c005a85a0bc827fcefbe"
EXPECTED_COMPILER = "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0"
ALLOWED_IMPORTS = {"alarm", "close", "fprintf", "fputs", "fstat", "ioctl", "memcmp", "memcpy",
                   "memset", "open", "printf", "puts", "sigaction", "sigemptyset", "snprintf",
                   "strcmp", "strlen", "stderr", "__fprintf_chk", "__printf_chk", "__snprintf_chk",
                   "__stack_chk_fail", "__stack_chk_guard"}
ABI_EXPECTED = {"pointer_bytes": 8, "card_info_bytes": 376, "elem_id_bytes": 64,
                "elem_list_bytes": 80, "list_pids_offset": 16, "elem_info_bytes": 272,
                "info_value_offset": 80, "elem_value_bytes": 1224, "read_value_offset": 72,
                "card_info_ioctl": "81785501", "list_ioctl": "c0505510",
                "info_ioctl": "c1105511", "read_ioctl": "c4c85512"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(path):
    if not path.is_file() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("Refuse missing or symlink input: " + str(path))


def fresh(path):
    if path.exists() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("Refuse existing or symlink output")
    if not path.resolve().is_relative_to((HERE / "build").resolve()):
        raise ValueError("Output escapes build directory")


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def saved_run(output, filename, argv):
    result = run(argv)
    (output / filename).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError(filename + " failed: " + result.stderr)
    return result


def evidence(label, phase):
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", label):
        raise ValueError("Evidence label must be red-vN or green-vN")
    directory = HERE / "build" / ("inspect-tests-" + label)
    path = directory / "result.json"
    plain(path)
    record = json.loads(path.read_text())
    for key, name in [("wrapper_sha256", "wrappers.c"), ("executable_sha256", "wrapped-inspect")]:
        plain(directory / name)
        if record[key] != sha(directory / name):
            raise ValueError("Changed compiled evidence: " + key)
    source = directory / "source-under-test.c"
    plain(source)
    if record["source_sha256"] != sha(source) or record["test_script_sha256"] != sha(TEST):
        raise ValueError("Evidence source or test script differs")
    if record["board_tested"] or record["real_alsa_device_access"]:
        raise ValueError("Offline intercepted device evidence required")
    if len(record["cases"]) != 114 or record["failures"] != sum(not c["passed"] for c in record["cases"]):
        raise ValueError("Incomplete or inconsistent test evidence")
    timer = next(c for c in record["cases"] if c["name"] == "actual-default-SIGALRM-deadline")
    if phase == "red":
        if not record["failures"] or record["source_sha256"] == sha(SOURCE) or timer["passed"] or not timer.get("external_test_deadline_expired"):
            raise ValueError("Actual C without the deadline must fail the timeout contract")
    else:
        if record["negative_control"] or record["failures"] or record["source_sha256"] != sha(SOURCE) or not timer["passed"]:
            raise ValueError("Current source must pass every actual C case")
        if phase == "arm" and (record["target"] != "AArch64 QEMU user with wrapped device calls" or record["qemu_sha256"] != sha(QEMU)):
            raise ValueError("Matching AArch64 QEMU evidence required")
        if phase == "host" and record["target"] != "host x86_64 wrapped device calls":
            raise ValueError("Matching host evidence required")
    return {"label": label, "result_sha256": sha(path), "source_sha256": record["source_sha256"],
            "wrapper_sha256": record["wrapper_sha256"], "executable_sha256": record["executable_sha256"],
            "cases": len(record["cases"]), "failures": record["failures"], "target": record["target"],
            "deadline_case": timer}


def abi_probe(output, label, header_flags):
    source = output / ("abi-" + label + ".c")
    # Including the real translation unit runs all its _Static_assert checks.
    source.write_text('#define main inspected_main\n#include "' + str(SOURCE) + '"\n#undef main\n' + r'''
int main(void)
{
    printf("{\"pointer_bytes\":%zu,\"card_info_bytes\":%zu,\"elem_id_bytes\":%zu,"
           "\"elem_list_bytes\":%zu,\"list_pids_offset\":%zu,\"elem_info_bytes\":%zu,"
           "\"info_value_offset\":%zu,\"elem_value_bytes\":%zu,\"read_value_offset\":%zu,"
           "\"card_info_ioctl\":\"%08lx\",\"list_ioctl\":\"%08lx\","
           "\"info_ioctl\":\"%08lx\",\"read_ioctl\":\"%08lx\"}\n",
           sizeof(void *), sizeof(struct snd_ctl_card_info), sizeof(struct snd_ctl_elem_id),
           sizeof(struct snd_ctl_elem_list), offsetof(struct snd_ctl_elem_list, pids),
           sizeof(struct snd_ctl_elem_info), offsetof(struct snd_ctl_elem_info, value),
           sizeof(struct snd_ctl_elem_value), offsetof(struct snd_ctl_elem_value, value),
           (unsigned long)SNDRV_CTL_IOCTL_CARD_INFO, (unsigned long)SNDRV_CTL_IOCTL_ELEM_LIST,
           (unsigned long)SNDRV_CTL_IOCTL_ELEM_INFO, (unsigned long)SNDRV_CTL_IOCTL_ELEM_READ);
    return 0;
}
''')
    executable = output / ("abi-" + label)
    argv = ["aarch64-linux-gnu-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-static",
            "-fno-ident", "-Wl,--build-id=none", *header_flags, str(source), "-o", str(executable)]
    saved_run(output, "abi-" + label + "-build.txt", argv)
    result = saved_run(output, "abi-" + label + "-result.txt", [str(QEMU), str(executable)])
    actual = json.loads(result.stdout)
    if actual != ABI_EXPECTED:
        raise ValueError("Actual compiled UAPI layout differs: " + label)
    return {"compile_argv": argv, "probe_source_sha256": sha(source),
            "probe_binary_sha256": sha(executable), "actual_layout": actual,
            "static_asserts_passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--red-evidence", default="red-v4")
    parser.add_argument("--host-evidence", default="green-v4")
    parser.add_argument("--arm-evidence", default="green-v5")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / "build" / ("inspect-" + args.version)
    fresh(output)
    for path in [SOURCE, TEST, Path(__file__).resolve(), LOCKED_UAPI, CROSS_UAPI, QEMU]:
        plain(path)
    if sha(LOCKED_UAPI) != EXPECTED_LOCKED or sha(CROSS_UAPI) != EXPECTED_CROSS:
        raise ValueError("Locked UAPI checksum differs")
    head = run(["git", "-C", str(KERNEL), "rev-parse", "HEAD"])
    if head.returncode or head.stdout.strip() != EXPECTED_HEAD:
        raise ValueError("Locked kernel source HEAD differs")
    compiler = run(["aarch64-linux-gnu-gcc", "--version"])
    if compiler.returncode or compiler.stdout.splitlines()[0] != EXPECTED_COMPILER:
        raise ValueError("Expected cross compiler unavailable")
    tests = {"actual_pre_deadline_red": evidence(args.red_evidence, "red"),
             "host": evidence(args.host_evidence, "host"), "aarch64_qemu": evidence(args.arm_evidence, "arm")}
    if tests["host"]["wrapper_sha256"] != tests["aarch64_qemu"]["wrapper_sha256"]:
        raise ValueError("Host and ARM fixtures differ")
    output.mkdir(parents=True)
    # The raw kernel UAPI retains sparse annotations removed by headers_install.
    # Erasing only those annotations preserves every actual field and type.
    locked_flags = ['-DALSA_LOCKED_UAPI="' + str(LOCKED_UAPI) + '"', "-D__user=", "-D__force="]
    abi = {"locked_kernel": abi_probe(output, "locked-kernel", locked_flags),
           "cross_compiler": abi_probe(output, "cross-compiler", [])}
    obj = output / "alsa-inspect.o"
    compile_argv = ["aarch64-linux-gnu-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-fno-builtin", "-fno-ident", *locked_flags, "-c", str(SOURCE), "-o", str(obj)]
    saved_run(output, "build-object.txt", compile_argv)
    imported = saved_run(output, "imports-object.txt", ["aarch64-linux-gnu-nm", "-u", str(obj)])
    names = sorted(line.split()[-1] for line in imported.stdout.splitlines() if line.strip())
    if not set(names).issubset(ALLOWED_IMPORTS) or not {"open", "fstat", "ioctl", "close", "alarm", "sigaction"}.issubset(names):
        raise ValueError("Unexpected production object imports: " + repr(names))
    binary = output / "alsa-inspect"
    link_argv = ["aarch64-linux-gnu-gcc", "-static", "-Wl,--build-id=none", str(obj), "-o", str(binary)]
    saved_run(output, "build-link.txt", link_argv)
    data = binary.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (2, 183):
        raise ValueError("Expected ELF64 LE AArch64 ET_EXEC")
    elf = saved_run(output, "readelf.txt", ["aarch64-linux-gnu-readelf", "-h", "-l", "-d", str(binary)])
    if "INTERP" in elf.stdout or "NEEDED" in elf.stdout:
        raise ValueError("Dynamic executable refused")
    symbols = saved_run(output, "symbols.txt", ["aarch64-linux-gnu-nm", str(binary)])
    symbol_names = {line.split()[-1] for line in symbols.stdout.splitlines() if line.strip()}
    # Static glibc crt1 legitimately defines __wrap_main; device/test wrappers do not.
    wrapper_names = {name for name in symbol_names if name.startswith("__wrap_") and name != "__wrap_main"}
    if wrapper_names or "inspect_main" in symbol_names:
        raise ValueError("Test wrapper or renamed test entry point in production binary")
    unresolved = saved_run(output, "imports-executable.txt", ["aarch64-linux-gnu-nm", "-u", str(binary)])
    if unresolved.stdout.strip():
        raise ValueError("Unresolved static executable import")
    arguments = []
    # No valid production invocation here: even a host device open is forbidden.
    for argv in [[], ["--help"], ["--inspect", "--card", "8"], ["--write", "--card", "2"]]:
        result = run([str(QEMU), str(binary), *argv])
        if result.returncode != 2 or result.stdout or "usage:" not in result.stderr:
            raise ValueError("Production QEMU argument rejection failed")
        arguments.append({"arguments": argv, "exit_code": result.returncode, "stderr": result.stderr})
    boundaries = []
    for version, diagnostic in [(args.version, "Refuse existing or symlink output"),
                                ("../outside", "version must be vN"), ("/tmp/inspect", "version must be vN")]:
        result = run([sys.executable, str(Path(__file__).resolve()), "--version", version])
        if result.returncode == 0 or diagnostic not in result.stderr:
            raise ValueError("Actual builder output refusal failed")
        boundaries.append({"version": version, "exit_code": result.returncode,
                           "expected_diagnostic": diagnostic, "stderr": result.stderr})
    manifest = {"license": "MIT", "source_sha256": sha(SOURCE), "test_script_sha256": sha(TEST),
                "builder_sha256": sha(Path(__file__).resolve()), "binary": "alsa-inspect",
                "binary_bytes": len(data), "binary_sha256": sha(binary),
                "binary_crc32": format(zlib.crc32(data), "08x"), "compiler": EXPECTED_COMPILER,
                "compile_argv": compile_argv, "link_argv": link_argv,
                "kernel_source_head": EXPECTED_HEAD, "uapi": {"locked_kernel_header_sha256": EXPECTED_LOCKED,
                    "cross_compiler_header_sha256": EXPECTED_CROSS, "compiled_abi": abi},
                "elf": "ELF64 LE AArch64 ET_EXEC", "no_interp": True, "no_needed": True,
                "production_object_imports": names, "static_executable_unresolved_imports": [],
                "no_test_wrapper_symbols": True, "qemu_sha256": sha(QEMU), "tests": tests,
                "production_qemu_argument_cases": arguments, "builder_refusal_tests": boundaries,
                "operation": {"arguments": ["--inspect", "--card", "N"], "card_range": [0, 7],
                    "path": "/dev/snd/controlCN", "open_flags": ["O_RDWR", "O_CLOEXEC", "O_NOFOLLOW", "O_NOCTTY"],
                    "character_major": 116, "minor": "dynamic; board runtime maps exact control node",
                    "required_card_id": "rockchiprk809co", "control_count_range": [2, 64],
                    "list_calls": 2, "enum_items_range": [1, 64], "maximum_target_controls": 3,
                    "target_control_identity": "MIXER, device/subdevice/index zero, unique dynamic nonzero numid",
                    "unknown_controls": "LIST only, valid interface/name and unique nonzero numid; never INFO or READ",
                    "allowed_ioctl_requests": ABI_EXPECTED | {"names": ["CARD_INFO", "ELEM_LIST", "ELEM_INFO", "ELEM_READ"]},
                    "required_cached_path_labels": {"Playback Path": "OFF", "Capture MIC Path": "MIC OFF"},
                    "resume_path": "optional; enum metadata and one cached value read, no OFF requirement",
                    "timeout_seconds": 5, "timeout_signal": "default SIGALRM; kernel releases descriptors on process termination",
                    "close_before_report_and_marker": True, "ioctl_return_required": 0,
                    "retries": 0, "writes": 0, "locks": 0, "pcm_opens": 0, "other_card_opens": 0},
                "success_marker": "ALSA_CODEC_INTERFACE_VERIFIED", "exit_codes": {"verified": 0, "rejected": 2,
                    "timeout": "terminated by SIGALRM"}, "board_tested": False, "real_alsa_device_access_on_host": False,
                "limitations": ["Target get callbacks read software caches; OFF does not prove electrical power or signal state",
                    "Wrapped host/QEMU tests establish ABI and failure handling, not codec or sound-card hardware behavior",
                    "No PCM playback, capture, control change, runtime lifecycle, MCLK, or electrical acceptance",
                    "The marker reports a bounded control-interface snapshot; it does not prove later state remains unchanged"]}
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"binary": str(binary), "bytes": len(data), "sha256": sha(binary),
                      "crc32": manifest["binary_crc32"], "manifest": str(path), "manifest_sha256": sha(path),
                      "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
