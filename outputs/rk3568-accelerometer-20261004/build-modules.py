#!/usr/bin/env python3
"""Build two external sensor modules against copies of the tested kernel ABI."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
ABI = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
IMAGE = ROOT / "outputs/rk3568-rcu-reset-20261004/Image"
PATCHES = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches"
RELEASE = "5.10.160-rt89-g9f9e9d18574d-dirty"
VERMAGIC = RELEASE + " SMP preempt_rt mod_unload aarch64"
LOCKS = {
    IMAGE: "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457",
    ABI / ".config": "1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912",
    ABI / "Module.symvers": "460aa3201dcc2c3486bfbb07e0fd36e810123314f004be236031cb569c7785d2",
    ABI / "include/generated/utsrelease.h": "1fe7b6626e1338222c11d5a054fe84d26279287bdc24e930b598f40259fcdb7a",
    PATCHES / "0001-arm64-cache-kasan-include.patch": "50fe5627b4fed8d765faf9210ab7ea5e5f74dcc7dd67cc2d4e3d2a3108c5619a",
    PATCHES / "0005-sensor-error-propagation.patch": "cff9f21c036173bc4465cf51ee414e77fc2456e8e0c15d84f0e74d414a64d184",
}
COPY_DIRS = ["include", "arch/arm64/include", "scripts"]
COPY_FILES = [".config", "Module.symvers", "vmlinux.symvers", "Makefile"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_command(argv):
    return subprocess.check_output(argv, text=True).strip()


def new_output(path):
    if path.exists() or path.is_symlink():
        raise ValueError("Refuse existing output: " + str(path))
    for parent in path.parents:
        if parent == ROOT:
            return
        if parent.is_symlink():
            raise ValueError("Refuse symlink output parent")
    raise ValueError("Output escaped repository")


def inventory(directory):
    result = {}
    for relative in COPY_DIRS + COPY_FILES:
        path = directory / relative
        if path.is_symlink():
            raise ValueError("ABI input cannot be a symlink: " + str(path))
        paths = sorted(path.rglob("*")) if path.is_dir() else [path]
        for member in paths:
            if member.is_symlink():
                raise ValueError("ABI input contains a symlink: " + str(member))
            if member.is_file():
                result[str(member.relative_to(directory))] = sha(member)
    return result


def symbols(path):
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 4:
            result[fields[1]] = {"provider": fields[2], "export_type": fields[3],
                                 "crc": fields[0], "namespace": fields[4] if len(fields) > 4 else ""}
    return result


def audit_module(module, output, kernel_exports, module_exports):
    data = module.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (1, 183):
        raise ValueError("Module is not little-endian AArch64 ET_REL: " + str(module))
    section = output / (module.name + ".modinfo")
    subprocess.run(["aarch64-linux-gnu-objcopy", "--dump-section", ".modinfo=" + str(section),
                    str(module)], check=True)
    metadata = {}
    for entry in section.read_bytes().split(b"\0"):
        if b"=" in entry:
            key, value = entry.decode().split("=", 1)
            metadata.setdefault(key, []).append(value)
    if metadata.get("vermagic", [""])[0].strip() != VERMAGIC:
        raise ValueError("Wrong module vermagic")
    if metadata.get("license") != ["GPL"]:
        raise ValueError("Unexpected module license")
    raw = read_command(["aarch64-linux-gnu-nm", "--undefined-only", str(module)])
    imports = {}
    for line in raw.splitlines():
        fields = line.split()
        if fields[-2] != "U":
            raise ValueError("Unreviewed weak/other import: " + line)
        name = fields[-1]
        if name in kernel_exports and kernel_exports[name]["provider"] == "vmlinux":
            imports[name] = kernel_exports[name]
        elif name in module_exports:
            imports[name] = module_exports[name]
        else:
            raise ValueError("Import not provided by this Image or paired module: " + name)
    dependency = metadata.get("depends", [""])[0]
    expected = "sensor_dev" if module.name == "mxc6655xa.ko" else ""
    if dependency != expected:
        raise ValueError("Wrong module dependency: " + dependency)
    (output / (module.name + ".undefined.txt")).write_text(raw + "\n")
    return {"bytes": len(data), "sha256": sha(module), "elf": "ELF64 LE AArch64 ET_REL",
            "metadata": metadata, "imports": imports, "imports_resolved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("driver-modules-" + args.version)
    new_output(output)
    if read_command(["git", "-C", str(KERNEL), "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("Unexpected source commit")
    if read_command(["git", "-C", str(KERNEL), "status", "--porcelain"]):
        raise ValueError("Source must stay clean")
    for path, digest in LOCKS.items():
        if sha(path) != digest:
            raise ValueError("Locked input mismatch: " + str(path))
    configuration = (ABI / ".config").read_text()
    for token in ["CONFIG_MODULES=y", "CONFIG_PREEMPT_RT=y", "# CONFIG_MODVERSIONS is not set",
                  "# CONFIG_SENSOR_DEVICE is not set"]:
        if token not in configuration.splitlines():
            raise ValueError("Unexpected ABI configuration: " + token)
    before = inventory(ABI)
    candidate = HERE / "driver-source-v1"
    source_manifest = candidate / "driver-source-manifest.json"
    source_record = json.loads(source_manifest.read_text())
    for relative, item in source_record["sources"].items():
        if sha(candidate / relative) != item["candidate_sha256"]:
            raise ValueError("Candidate source changed: " + relative)
        if sha(KERNEL / relative) != item["original_sha256"]:
            raise ValueError("Original source changed: " + relative)
    green = HERE / "driver-tests-green-v2/result.json"
    green_record = json.loads(green.read_text())
    if green_record["exit_code"] != 0:
        raise ValueError("Real-function tests must pass first")
    for path, digest in green_record["source_sha256"].items():
        if sha(ROOT / path) != digest:
            raise ValueError("Tested source changed")
    output.mkdir()
    replay = output / "patch-replay"
    replay.mkdir()
    for relative in source_record["sources"]:
        replay_member = replay / relative
        replay_member.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(KERNEL / relative, replay_member)
    patch_replay = subprocess.run(["patch", "--batch", "-p1", "-d", str(replay), "-i",
                                   str(PATCHES / "0005-sensor-error-propagation.patch")],
                                  capture_output=True, text=True)
    (output / "sensor-patch.txt").write_text(patch_replay.stdout + patch_replay.stderr)
    if patch_replay.returncode:
        raise ValueError("Sensor patch replay failed")
    for relative in source_record["sources"]:
        if sha(replay / relative) != sha(candidate / relative):
            raise ValueError("Candidate is not exactly the published patch result: " + relative)
    shadow = output / "kernel-abi"
    shadow.mkdir()
    for relative in COPY_DIRS:
        shutil.copytree(ABI / relative, shadow / relative)
    for relative in COPY_FILES:
        shutil.copy2(ABI / relative, shadow / relative)
    if inventory(shadow) != before:
        raise ValueError("Copied ABI metadata differs")
    overlay = output / "include-overlay"
    header = overlay / "arch/arm64/include/asm/cache.h"
    header.parent.mkdir(parents=True)
    shutil.copy2(KERNEL / "arch/arm64/include/asm/cache.h", header)
    patched = subprocess.run(["patch", "--batch", "-p1", "-d", str(overlay), "-i",
                              str(PATCHES / "0001-arm64-cache-kasan-include.patch")],
                             capture_output=True, text=True)
    (output / "cache-patch.txt").write_text(patched.stdout + patched.stderr)
    if patched.returncode:
        raise ValueError("Tested cache header overlay failed")
    module_dir = output / "modules"
    module_dir.mkdir()
    for relative in source_record["sources"]:
        shutil.copy2(candidate / relative, module_dir / Path(relative).name)
    kbuild = ("# Explicit external module selection; tested kernel .config is unchanged.\n"
              "obj-m += sensor_dev.o\n"
              "sensor_dev-y := sensor-i2c.o sensor-dev.o\n"
              "obj-m += mxc6655xa.o\n")
    (module_dir / "Makefile").write_text(kbuild)
    include_paths = [overlay / "arch/arm64/include", KERNEL / "arch/arm64/include",
                     shadow / "arch/arm64/include/generated", KERNEL / "include", shadow / "include",
                     KERNEL / "arch/arm64/include/uapi", shadow / "arch/arm64/include/generated/uapi",
                     KERNEL / "include/uapi", shadow / "include/generated/uapi"]
    include = " ".join("-I" + str(path) for path in include_paths)
    include += " -include " + str(KERNEL / "include/linux/kconfig.h")
    argv = ["make", "-C", str(shadow), "M=" + str(module_dir), "ARCH=arm64",
            "CROSS_COMPILE=aarch64-linux-gnu-", "LINUXINCLUDE=" + include, "V=1", "-j2", "modules"]
    compiler = read_command(["aarch64-linux-gnu-gcc", "--version"]).splitlines()[0]
    if compiler != 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0':
        raise ValueError("Compiler differs from tested Image compiler")
    built = subprocess.run(argv, capture_output=True, text=True)
    (output / "build.txt").write_text(built.stdout + built.stderr)
    (output / "build-argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    if inventory(ABI) != before:
        raise ValueError("Original ABI metadata changed")
    if read_command(["git", "-C", str(KERNEL), "status", "--porcelain"]):
        raise ValueError("Original source changed during build")
    if built.returncode:
        raise ValueError("Module build failed; preserved build.txt")
    kernel_exports = symbols(shadow / "Module.symvers")
    module_exports = symbols(module_dir / "Module.symvers")
    audits = {name: audit_module(module_dir / name, output, kernel_exports, module_exports)
              for name in ["sensor_dev.ko", "mxc6655xa.ko"]}
    if "rk_vendor_read" not in audits["sensor_dev.ko"]["imports"]:
        raise ValueError("Expected calibration dependency was not audited")
    record = {"source_commit": COMMIT, "source_clean_after_build": True,
              "tested_image_sha256": sha(IMAGE), "tested_image_bytes": IMAGE.stat().st_size,
              "kernel_release": RELEASE, "compiler": compiler, "build_argv": argv,
              "locked_input_sha256": {str(path.relative_to(ROOT)): digest for path, digest in LOCKS.items()},
              "source_manifest_sha256": sha(source_manifest), "real_function_tests_sha256": sha(green),
              "builder_sha256": sha(Path(__file__)), "patch_replay_matches_candidate": True,
              "abi_metadata_sha256": before, "original_abi_metadata_unchanged": True,
              "copied_config_sha256": sha(shadow / ".config"),
              "cache_header_overlay_sha256": sha(header),
              "original_kbuild_sha256": {relative: sha(KERNEL / relative) for relative in [
                  "drivers/input/sensors/Makefile", "drivers/input/sensors/accel/Makefile"]},
              "external_kbuild_sha256": sha(module_dir / "Makefile"), "module_exports": module_exports,
              "modules": audits, "module_selection": "External obj-m, no kernel config change",
              "modversions": False, "board_tested": False, "kernel_module_loaded_on_host": False,
              "unload_safe": False, "calibration_called": False,
              "limitations": ["Mock functions prove error flow, not I2C hardware response",
                              "Import closure and exact headers/config bind the candidate to this Image; board loading is pending",
                              "Existing remove/calibration concurrency lifecycle is not fixed; first trial requires RAM-only reset and no calibration"]}
    (output / "module-manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(output), "modules": {name: {key: item[key] for key in ["bytes", "sha256", "elf"]}
                                                            for name, item in audits.items()},
                      "vermagic": VERMAGIC, "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
