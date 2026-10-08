#!/usr/bin/env python3
"""Build the RK817 external module using private copies of the tested Image ABI."""
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
IMAGE = ROOT / "outputs/rk3568-rcu-reset-20261004/Image"
PATCHES = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches"
PATCH = PATCHES / "0006-rk817-codec-error-propagation.patch"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
RELEASE = "5.10.160-rt89-g9f9e9d18574d-dirty"
VERMAGIC = RELEASE + " SMP preempt_rt mod_unload aarch64"
LOCKS = {
    IMAGE: "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457",
    ABI / ".config": "1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912",
    ABI / "Module.symvers": "460aa3201dcc2c3486bfbb07e0fd36e810123314f004be236031cb569c7785d2",
    ABI / "include/generated/utsrelease.h": "1fe7b6626e1338222c11d5a054fe84d26279287bdc24e930b598f40259fcdb7a",
    PATCHES / "0001-arm64-cache-kasan-include.patch": "50fe5627b4fed8d765faf9210ab7ea5e5f74dcc7dd67cc2d4e3d2a3108c5619a",
    PATCH: "f501e5642d363b0c10431de053c19d8c1ae16060ddb35838d520de0f0d84bd81",
}
COPY_DIRS = ["include", "arch/arm64/include", "scripts"]
COPY_FILES = [".config", "Module.symvers", "vmlinux.symvers", "Makefile"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv):
    return subprocess.check_output(argv, text=True).strip()


def ordinary_input(path):
    for member in [path, *path.parents]:
        if member == ROOT:
            break
        if member.is_symlink():
            raise ValueError("Refuse symlink input: " + str(member))
    else:
        raise ValueError("Input escaped repository")
    if not path.is_file():
        raise ValueError("Missing ordinary input: " + str(path))


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
        if path.is_symlink() or not path.exists():
            raise ValueError("Missing or symlink ABI input: " + str(path))
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


def audit_module(module, output, kernel_exports):
    data = module.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (1, 183):
        raise ValueError("Module must be ELF64 LE AArch64 ET_REL")
    header = command(["aarch64-linux-gnu-readelf", "-h", "-l", "-d", "-S", str(module)])
    if "INTERP" in header or "NEEDED" in header:
        raise ValueError("Module contains dynamic ELF dependencies")
    (output / "module-readelf.txt").write_text(header + "\n")
    section = output / "module.modinfo"
    subprocess.run(["aarch64-linux-gnu-objcopy", "--dump-section", ".modinfo=" + str(section),
                    str(module)], check=True)
    metadata = {}
    for entry in section.read_bytes().split(b"\0"):
        if b"=" in entry:
            key, value = entry.decode().split("=", 1)
            metadata.setdefault(key, []).append(value)
    if metadata.get("vermagic") != [VERMAGIC]:
        raise ValueError("Wrong module vermagic")
    if metadata.get("license") != ["GPL v2"] or metadata.get("name") != ["snd_soc_rk817"]:
        raise ValueError("Unexpected module license/name")
    if metadata.get("depends") != [""]:
        raise ValueError("Unexpected external module dependencies")
    if not any("rockchip,rk817-codec" in alias for alias in metadata.get("alias", [])):
        raise ValueError("Missing codec OF module alias")
    raw = command(["aarch64-linux-gnu-nm", "--undefined-only", str(module)])
    imports = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[0] != "U":
            raise ValueError("Unreviewed weak/other module import: " + line)
        name = fields[1]
        item = kernel_exports.get(name)
        if not item or item["provider"] != "vmlinux" or item["namespace"]:
            raise ValueError("Import is not available from the exact Image: " + name)
        imports[name] = item
    for required in ["regmap_read", "snd_soc_component_write", "snd_soc_component_update_bits",
                     "snd_soc_add_component_controls", "devm_snd_soc_register_component",
                     "clk_prepare", "clk_enable"]:
        if required not in imports:
            raise ValueError("Expected real driver import missing: " + required)
    if {"snd_soc_component_exit_regmap", "__devm_regmap_init_i2c", "__regmap_init_i2c", "regmap_exit", "devm_add_action"} & set(imports):
        raise ValueError("Module must only borrow the original PMIC map, without new allocation or release")
    (output / "module-undefined.txt").write_text(raw + "\n")
    defined = command(["aarch64-linux-gnu-nm", "--defined-only", str(module)])
    (output / "module-defined.txt").write_text(defined + "\n")
    return {"bytes": len(data), "sha256": sha(module), "elf": "ELF64 LE AArch64 ET_REL",
            "metadata": metadata, "imports": imports, "imports_resolved": True,
            "elf_has_interp": False, "elf_has_needed": False, "defined_symbols_recorded": True}


def check_locks():
    for path, digest in LOCKS.items():
        ordinary_input(path)
        if sha(path) != digest:
            raise ValueError("Locked input mismatch: " + str(path))
    if command(["git", "-C", str(KERNEL), "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("Unexpected source commit")
    if command(["git", "-C", str(KERNEL), "status", "--porcelain"]):
        raise ValueError("Locked kernel source must stay clean")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("driver-modules-" + args.version)
    new_output(output)
    check_locks()
    configuration = (ABI / ".config").read_text().splitlines()
    for token in ["CONFIG_MODULES=y", "CONFIG_PREEMPT_RT=y", "# CONFIG_MODVERSIONS is not set",
                  "# CONFIG_SND_SOC_RK817 is not set", "CONFIG_REGMAP_I2C=y", "CONFIG_SND_SOC=y"]:
        if token not in configuration:
            raise ValueError("Unexpected ABI configuration: " + token)
    before = inventory(ABI)
    candidate_dir = HERE / "driver-source-v5"
    source_manifest = candidate_dir / "driver-source-manifest.json"
    ordinary_input(source_manifest)
    source_record = json.loads(source_manifest.read_text())
    if source_record["patch_sha256"] != sha(PATCH) or source_record["source_commit"] != COMMIT:
        raise ValueError("Candidate manifest does not match locked patch/source")
    for relative, item in source_record["sources"].items():
        if relative not in ["sound/soc/codecs/rk817_codec.c", "sound/soc/codecs/rk817_codec.h"]:
            raise ValueError("Unexpected candidate path")
        ordinary_input(candidate_dir / relative)
        if sha(candidate_dir / relative) != item["candidate_sha256"] or sha(KERNEL / relative) != item["original_sha256"]:
            raise ValueError("Candidate/original source mismatch: " + relative)
    tests = [HERE / "driver-tests-green-v5/result.json", HERE / "driver-tests-green-v6/result.json"]
    for test in tests:
        ordinary_input(test)
        record = json.loads(test.read_text())
        if record["exit_code"] or record["total"] != 73 or record["passed"] != 73:
            raise ValueError("Real-function fault tests must pass before build")
        for relative, digest in record["source_sha256"].items():
            if sha(ROOT / relative) != digest:
                raise ValueError("Tested driver source changed")
        for name, digest in record["test_input_sha256"].items():
            if sha(HERE / name) != digest:
                raise ValueError("Test implementation changed since green run")
    compiler = command(["aarch64-linux-gnu-gcc", "--version"]).splitlines()[0]
    if compiler != "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0":
        raise ValueError("Compiler differs from the tested Image compiler")
    output.mkdir()
    replay = output / "patch-replay"
    replay.mkdir()
    for relative in source_record["sources"]:
        target = replay / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(KERNEL / relative, target)
    patched = subprocess.run(["patch", "--batch", "-p1", "-d", str(replay), "-i", str(PATCH)],
                             capture_output=True, text=True)
    (output / "codec-patch.txt").write_text(patched.stdout + patched.stderr)
    if patched.returncode:
        raise ValueError("Published codec patch replay failed")
    for relative in source_record["sources"]:
        if sha(replay / relative) != sha(candidate_dir / relative):
            raise ValueError("Published patch result differs from candidate")
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
        shutil.copy2(candidate_dir / relative, module_dir / Path(relative).name)
    kbuild = "# Explicit external selection; original .config is unchanged.\n"
    kbuild += "obj-m += snd-soc-rk817.o\nsnd-soc-rk817-objs := rk817_codec.o\n"
    (module_dir / "Makefile").write_text(kbuild)
    include_paths = [overlay / "arch/arm64/include", KERNEL / "arch/arm64/include",
                     shadow / "arch/arm64/include/generated", KERNEL / "include", shadow / "include",
                     KERNEL / "arch/arm64/include/uapi", shadow / "arch/arm64/include/generated/uapi",
                     KERNEL / "include/uapi", shadow / "include/generated/uapi"]
    include = " ".join("-I" + str(path) for path in include_paths)
    include += " -include " + str(KERNEL / "include/linux/kconfig.h")
    argv = ["make", "-C", str(shadow), "M=" + str(module_dir), "ARCH=arm64",
            "CROSS_COMPILE=aarch64-linux-gnu-", "LINUXINCLUDE=" + include, "V=1", "-j2", "modules"]
    built = subprocess.run(argv, capture_output=True, text=True)
    (output / "build.txt").write_text(built.stdout + built.stderr)
    (output / "build-argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    check_locks()
    if inventory(ABI) != before:
        raise ValueError("Original ABI metadata changed during build")
    if built.returncode:
        raise ValueError("Codec module build failed; see preserved build.txt")
    exports = symbols(shadow / "Module.symvers")
    own_exports = symbols(module_dir / "Module.symvers")
    if own_exports:
        raise ValueError("Unexpected codec module exports")
    module = module_dir / "snd-soc-rk817.ko"
    audit = audit_module(module, output, exports)
    record = {
        "source_commit": COMMIT, "source_clean_after_build": True,
        "tested_image_sha256": sha(IMAGE), "tested_image_bytes": IMAGE.stat().st_size,
        "kernel_release": RELEASE, "compiler": compiler, "build_argv": argv,
        "locked_input_sha256": {str(path.relative_to(ROOT)): digest for path, digest in LOCKS.items()},
        "source_manifest_sha256": sha(source_manifest), "candidate_source_record": source_record,
        "real_function_tests_sha256": {str(test.relative_to(HERE)): sha(test) for test in tests},
        "builder_sha256": sha(Path(__file__)), "patch_replay_matches_candidate": True,
        "abi_metadata_sha256": before, "original_abi_metadata_unchanged": True,
        "copied_config_sha256": sha(shadow / ".config"), "cache_header_overlay_sha256": sha(header),
        "original_kbuild_sha256": {relative: sha(KERNEL / relative) for relative in [
            "sound/soc/codecs/Makefile", "sound/soc/codecs/Kconfig"]},
        "external_kbuild_sha256": sha(module_dir / "Makefile"), "module_exports": own_exports,
        "modules": {module.name: audit}, "module_selection": "External obj-m; original CONFIG_SND_SOC_RK817=n unchanged",
        "modversions": False, "board_tested": False, "kernel_module_loaded_on_host": False,
        "runtime_pcm_paths_fixed": False, "unload_safe": False,
        "limitations": source_record["limitations"] + [
            "Import closure and exact headers/config bind this candidate to the Image, not to verified board loading",
            "No PCM open, control writes, playback/capture, suspend or concurrent removal tested"]}
    (output / "module-manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(output), "module": module.name, "bytes": audit["bytes"],
                      "sha256": audit["sha256"], "imports": len(audit["imports"]),
                      "vermagic": VERMAGIC, "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
