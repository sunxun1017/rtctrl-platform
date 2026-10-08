#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the static AArch64 no-start PCM helper with locked UAPI and offline evidence."""
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
SOURCE = HERE / "pcm-config.c"
TEST = HERE / "test-pcm-config.py"
KERNEL = ROOT / "third_party/linux-rk3588"
UAPI = KERNEL / "include/uapi/sound/asound.h"
CROSS_UAPI = Path("/usr/aarch64-linux-gnu/include/sound/asound.h")
CONFIG = ROOT / "outputs/rk3568-source-userspace-20261004/kernel.config"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
EXPECTED_UAPI = "138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447"
EXPECTED_CROSS = "b62c8bff11f4aeea5df38899dbb2e18af10c0ffba770c005a85a0bc827fcefbe"
EXPECTED_CONFIG = "1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912"
EXPECTED_COMPILER = "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0"
ALLOWED_IMPORTS = {"__errno_location", "alarm", "close", "fprintf", "fstat", "ioctl", "memcmp", "memset", "open", "printf", "puts", "sigaction", "sigaddset", "sigemptyset", "sigprocmask", "snprintf", "strcmp", "strlen", "stderr", "__fprintf_chk", "__printf_chk", "__snprintf_chk", "__stack_chk_fail", "__stack_chk_guard"}
ABI = {"pointer_bytes": 8, "long_bytes": 8, "time_bytes": 8, "card_info_bytes": 376,
       "pcm_info_bytes": 288, "id_offset": 16, "name_offset": 80, "mask_bytes": 32,
       "interval_bytes": 12, "hw_params_bytes": 608, "masks_offset": 4,
       "intervals_offset": 260, "rmask_offset": 512, "fifo_size_offset": 536,
       "status_bytes": 152, "appl_ptr_offset": 40, "hw_ptr_offset": 48,
       "card_info_ioctl": "81785501", "pversion_ioctl": "80044100", "info_ioctl": "81204101",
       "refine_ioctl": "c2604110", "params_ioctl": "c2604111", "free_ioctl": "00004112", "status_ioctl": "80984120"}


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


def saved_run(output, label, argv):
    result = run(argv)
    (output / label).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError(label + " failed: " + result.stderr)
    return result


def evidence(label, phase):
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", label):
        raise ValueError("Evidence label must be red-vN or green-vN")
    directory = HERE / "build" / ("pcm-tests-" + label)
    path = directory / "result.json"
    plain(path)
    record = json.loads(path.read_text())
    for key, name in [("source_sha256", "source-under-test.c"), ("wrapper_sha256", "wrappers.c"), ("executable_sha256", "wrapped-pcm-config")]:
        plain(directory / name)
        if record[key] != sha(directory / name):
            raise ValueError("Changed test evidence: " + key)
    if record["test_script_sha256"] != sha(TEST) or record["locked_uapi_sha256"] != sha(UAPI):
        raise ValueError("Current test/UAPI evidence differs")
    if len(record["cases"]) != 180 or record["failures"] != sum(not c["passed"] for c in record["cases"]):
        raise ValueError("Incomplete or inconsistent test evidence")
    if record["board_tested"] or record["real_alsa_device_access"]:
        raise ValueError("Offline wrapped tests required")
    timer = next(c for c in record["cases"] if c["name"] == "actual-default-SIGALRM-deadline-inherited-block-and-ignore")
    if phase == "red":
        if not record["negative_control"] or not record["failures"] or record["source_sha256"] == sha(SOURCE):
            raise ValueError("A compiled missing-contract red baseline is required")
    else:
        if record["negative_control"] or record["failures"] or record["source_sha256"] != sha(SOURCE) or not timer["passed"]:
            raise ValueError("Current source must pass all tests")
        expected = "AArch64 QEMU user with wrapped device calls" if phase == "arm" else "host x86_64 wrapped device calls"
        if record["target"] != expected or (phase == "arm" and record["qemu_sha256"] != sha(QEMU)):
            raise ValueError("Test target differs")
    return {"label": label, "result_sha256": sha(path), "source_sha256": record["source_sha256"],
            "wrapper_sha256": record["wrapper_sha256"], "executable_sha256": record["executable_sha256"],
            "cases": len(record["cases"]), "failures": record["failures"], "target": record["target"], "deadline_case": timer}


def abi_probe(output, label, flags):
    source = output / ("abi-" + label + ".c")
    source.write_text('#define main pcm_config_probed_main\n#include "' + str(SOURCE) + '"\n#undef main\n' + r'''
int main(void)
{
    printf("{\"pointer_bytes\":%zu,\"long_bytes\":%zu,\"time_bytes\":%zu,\"card_info_bytes\":%zu,"
           "\"pcm_info_bytes\":%zu,\"id_offset\":%zu,\"name_offset\":%zu,\"mask_bytes\":%zu,"
           "\"interval_bytes\":%zu,\"hw_params_bytes\":%zu,\"masks_offset\":%zu,\"intervals_offset\":%zu,"
           "\"rmask_offset\":%zu,\"fifo_size_offset\":%zu,\"status_bytes\":%zu,\"appl_ptr_offset\":%zu,\"hw_ptr_offset\":%zu,"
           "\"card_info_ioctl\":\"%08lx\",\"pversion_ioctl\":\"%08lx\",\"info_ioctl\":\"%08lx\","
           "\"refine_ioctl\":\"%08lx\",\"params_ioctl\":\"%08lx\",\"free_ioctl\":\"%08lx\",\"status_ioctl\":\"%08lx\"}\n",
           sizeof(void *), sizeof(long), sizeof(time_t), sizeof(struct snd_ctl_card_info),
           sizeof(struct snd_pcm_info), offsetof(struct snd_pcm_info, id), offsetof(struct snd_pcm_info, name), sizeof(struct snd_mask),
           sizeof(struct snd_interval), sizeof(struct snd_pcm_hw_params), offsetof(struct snd_pcm_hw_params, masks), offsetof(struct snd_pcm_hw_params, intervals),
           offsetof(struct snd_pcm_hw_params, rmask), offsetof(struct snd_pcm_hw_params, fifo_size), sizeof(struct snd_pcm_status), offsetof(struct snd_pcm_status, appl_ptr), offsetof(struct snd_pcm_status, hw_ptr),
           (unsigned long)SNDRV_CTL_IOCTL_CARD_INFO, (unsigned long)SNDRV_PCM_IOCTL_PVERSION, (unsigned long)SNDRV_PCM_IOCTL_INFO,
           (unsigned long)SNDRV_PCM_IOCTL_HW_REFINE, (unsigned long)SNDRV_PCM_IOCTL_HW_PARAMS, (unsigned long)SNDRV_PCM_IOCTL_HW_FREE, (unsigned long)SNDRV_PCM_IOCTL_STATUS);
    return 0;
}
''')
    binary = output / ("abi-" + label)
    argv = ["aarch64-linux-gnu-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-static", "-fno-ident", "-Wl,--build-id=none", *flags, str(source), "-o", str(binary)]
    saved_run(output, "abi-" + label + "-compile.txt", argv)
    result = saved_run(output, "abi-" + label + "-result.txt", [str(QEMU), str(binary)])
    actual = json.loads(result.stdout)
    if actual != ABI:
        raise ValueError("Compiled UAPI differs: " + label)
    return {"compile_argv": argv, "source_sha256": sha(source), "binary_sha256": sha(binary), "actual_layout": actual, "production_static_asserts_passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--red-evidence", default="red-v3")
    parser.add_argument("--host-evidence", default="green-v3")
    parser.add_argument("--arm-evidence", default="green-v4")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / "build" / ("pcm-production-" + args.version)
    fresh(output)
    for path in [SOURCE, TEST, Path(__file__).resolve(), UAPI, CROSS_UAPI, CONFIG, QEMU]:
        plain(path)
    if sha(UAPI) != EXPECTED_UAPI or sha(CROSS_UAPI) != EXPECTED_CROSS or sha(CONFIG) != EXPECTED_CONFIG:
        raise ValueError("Locked input checksum differs")
    if "CONFIG_SND_DYNAMIC_MINORS=y" not in CONFIG.read_text().splitlines():
        raise ValueError("Expected dynamic ALSA minor configuration differs")
    compiler = run(["aarch64-linux-gnu-gcc", "--version"])
    if compiler.returncode or compiler.stdout.splitlines()[0] != EXPECTED_COMPILER:
        raise ValueError("Expected GCC 11.4 compiler unavailable")
    tests = {"missing_contract_red": evidence(args.red_evidence, "red"), "host": evidence(args.host_evidence, "host"), "aarch64_qemu": evidence(args.arm_evidence, "arm")}
    if tests["host"]["wrapper_sha256"] != tests["aarch64_qemu"]["wrapper_sha256"]:
        raise ValueError("Host and AArch64 fixtures differ")
    output.mkdir(parents=True)
    flags = ['-DALSA_LOCKED_UAPI="' + str(UAPI) + '"', "-D__user=", "-D__force="]
    abi = {"locked_kernel": abi_probe(output, "locked-kernel", flags), "cross_compiler": abi_probe(output, "cross-compiler", [])}
    obj = output / "pcm-config.o"
    compile_argv = ["aarch64-linux-gnu-gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-builtin", "-fno-ident", *flags, "-c", str(SOURCE), "-o", str(obj)]
    saved_run(output, "compile-object.txt", compile_argv)
    imports = saved_run(output, "imports-object.txt", ["aarch64-linux-gnu-nm", "-u", str(obj)])
    imported = sorted(line.split()[-1] for line in imports.stdout.splitlines() if line.strip())
    if not set(imported).issubset(ALLOWED_IMPORTS) or not {"open", "fstat", "ioctl", "close", "alarm", "sigaction", "sigprocmask"}.issubset(imported):
        raise ValueError("Unexpected production imports: " + repr(imported))
    binary = output / "pcm-config"
    link_argv = ["aarch64-linux-gnu-gcc", "-static", "-Wl,--build-id=none", str(obj), "-o", str(binary)]
    saved_run(output, "link-static.txt", link_argv)
    data = binary.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (2, 183):
        raise ValueError("Expected ELF64 LE AArch64 ET_EXEC")
    elf = saved_run(output, "readelf.txt", ["aarch64-linux-gnu-readelf", "-h", "-l", "-d", str(binary)])
    if "INTERP" in elf.stdout or "NEEDED" in elf.stdout:
        raise ValueError("Dynamic executable refused")
    symbols = saved_run(output, "symbols.txt", ["aarch64-linux-gnu-nm", str(binary)])
    names = {line.split()[-1] for line in symbols.stdout.splitlines() if line.strip()}
    if {name for name in names if name.startswith("__wrap_") and name != "__wrap_main"} or "pcm_config_main" in names or "scenario" in names:
        raise ValueError("Test wrapper in production executable")
    unresolved = saved_run(output, "imports-executable.txt", ["aarch64-linux-gnu-nm", "-u", str(binary)])
    if unresolved.stdout.strip():
        raise ValueError("Unresolved static import")
    rejected = []
    for argv in [[], ["--help"], ["--configure", "--card", "8", "--stream", "playback"], ["--configure", "--card", "2", "--stream", "both"]]:
        result = run([str(QEMU), str(binary), *argv])
        if result.returncode != 2 or result.stdout or "usage:" not in result.stderr:
            raise ValueError("Production argument rejection failed")
        rejected.append({"arguments": argv, "exit_code": result.returncode, "stderr": result.stderr})
    boundaries = []
    for version, diagnostic in [(args.version, "Refuse existing or symlink output"), ("../escape", "version must be vN"), ("/tmp/pcm", "version must be vN")]:
        result = run([sys.executable, str(Path(__file__).resolve()), "--version", version])
        if not result.returncode or diagnostic not in result.stderr:
            raise ValueError("Builder output refusal failed")
        boundaries.append({"version": version, "exit_code": result.returncode, "expected_diagnostic": diagnostic, "stderr": result.stderr})
    identity_sources = ["sound/soc/generic/simple-card.c", "sound/soc/generic/simple-card-utils.c", "sound/soc/soc-pcm.c", "sound/soc/soc-generic-dmaengine-pcm.c", "sound/core/pcm_native.c", "include/sound/minors.h"]
    identity_evidence = {name: sha(KERNEL / name) for name in identity_sources}
    manifest = {"license": "MIT", "source_sha256": sha(SOURCE), "test_script_sha256": sha(TEST), "builder_sha256": sha(Path(__file__)), "binary": binary.name, "binary_bytes": len(data), "binary_sha256": sha(binary), "binary_crc32": format(zlib.crc32(data), "08x"), "compiler": EXPECTED_COMPILER, "compile_argv": compile_argv, "link_argv": link_argv,
                "uapi": {"locked_kernel_header_sha256": sha(UAPI), "cross_compiler_header_sha256": sha(CROSS_UAPI), "compiled_abi": abi}, "kernel_config_sha256": sha(CONFIG), "identity_source_sha256": identity_evidence,
                "elf": "ELF64 LE AArch64 ET_EXEC", "no_interp": True, "no_needed": True, "production_object_imports": imported, "static_executable_unresolved_imports": [], "no_test_wrapper_symbols": True, "qemu_sha256": sha(QEMU), "tests": tests,
                "production_qemu_argument_cases": rejected, "builder_refusal_tests": boundaries,
                "operation": {"arguments": ["--configure", "--card", "N", "--stream", "playback|capture"], "card_range": [0, 7], "control_path": "/dev/snd/controlCN", "pcm_path": "/dev/snd/pcmCND0p|c", "open_flags": ["O_RDWR", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK", "O_NOCTTY"], "character_major": 116, "minor": "dynamic; exact kernel CONFIG_SND_DYNAMIC_MINORS=y; strict card and PCM INFO identity instead of fixed-minor assumptions", "required_card_id": "rockchiprk809co", "required_pcm_id_and_name": "fe410000.i2s-rk817-hifi rk817-hifi-0", "required_pcm_device": 0, "required_pcm_subdevice": 0, "required_protocol_version": "2.0.15",
                              "control_ioctl_allowlist": ["CARD_INFO"], "pcm_ioctl_allowlist": ["PVERSION", "INFO", "HW_REFINE", "HW_PARAMS", "STATUS", "HW_FREE"], "normal_sequence": ["control open/fstat/CARD_INFO/close", "PCM open/fstat/PVERSION/INFO", "HW_REFINE full range and capability output", "HW_REFINE exact parameters", "HW_PARAMS", "STATUS SETUP with appl_ptr=hw_ptr=0", "HW_FREE", "STATUS OPEN", "PCM close", "cancel alarm", "success marker"], "exact_parameters": {"access": "RW_INTERLEAVED", "format": "S16_LE", "subformat": "STD", "sample_bits": 16, "frame_bits": 32, "rate": 48000, "channels": 2, "period_size": 256, "period_bytes": 1024, "periods": 4, "buffer_size": 1024, "buffer_bytes": 4096}, "timeout_seconds": 5, "timeout_signal": "default SIGALRM, explicitly unblocked; process termination releases descriptors", "first_error_preserved_through_cleanup": True, "close_failure_is_failure": True, "successful_params_always_free_before_close": True, "ioctl_return_required": 0, "retries": 0, "prepare": 0, "start": 0, "drop": 0, "frame_reads_writes": 0, "mmap": 0, "control_writes": 0},
                "success_marker": "PCM_CONFIGURATION_VERIFIED_NO_START", "board_tested": False, "real_alsa_device_access_on_host": False,
                "limitations": ["Offline syscall-wrapped tests establish ABI, call selection and cleanup; target PCM hardware remains untested", "HW_PARAMS may configure I2S/codec clocks and DMA slave_config; it does not submit or start a DMA transfer", "No PREPARE/START, PCM frame transfer, sound quality, channel mapping, electrical or acoustic acceptance", "Control identity and PCM identity are separate snapshots; concurrent device removal or audio activity cannot be excluded", "The caller must separately verify OFF/MIC OFF paths and absence of other audio users on the target", "Default SIGALRM bounds normal user-mode progress but cannot force immediate scheduling or a driver stuck in uninterruptible kernel sleep"]}
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"binary": str(binary), "bytes": len(data), "sha256": sha(binary), "crc32": manifest["binary_crc32"], "manifest": str(path), "manifest_sha256": sha(path), "tests_per_target": 180, "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
