#!/usr/bin/env python3
"""Compile the complete candidate against copied, locked kernel ABI metadata."""
import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
ABI = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
SOURCE = "sound/soc/rockchip/rockchip_i2s_tdm.c"
COPY_DIRS = ["include", "arch/arm64/include", "scripts"]
COPY_FILES = [".config", "Module.symvers", "vmlinux.symvers", "Makefile"]
CACHE_PATCH = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches/0001-arm64-cache-kasan-include.patch"
DTB = ROOT / "outputs/rk3568-audio-20261005/build/staging-v1/audio.dtb"
LOCKS = {
    KERNEL / SOURCE: "53de554206b13f13e480280b8f46366778c2837cdcba2cdb1417e0127be7ffda",
    ABI / ".config": "1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912",
    ABI / "Module.symvers": "460aa3201dcc2c3486bfbb07e0fd36e810123314f004be236031cb569c7785d2",
    CACHE_PATCH: "50fe5627b4fed8d765faf9210ab7ea5e5f74dcc7dd67cc2d4e3d2a3108c5619a",
    DTB: "9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv):
    return subprocess.check_output([str(a) for a in argv], text=True).strip()


def ordinary(path):
    for member in [path, *path.parents]:
        if member == ROOT:
            break
        if member.is_symlink():
            raise ValueError("symlink input: " + str(member))
    else:
        raise ValueError("input escaped repository")
    if not path.is_file():
        raise ValueError("missing ordinary input: " + str(path))


def inventory(directory):
    result = {}
    for relative in COPY_DIRS + COPY_FILES:
        path = directory / relative
        if path.is_symlink() or not path.exists():
            raise ValueError("missing/symlink ABI input")
        for member in sorted(path.rglob("*")) if path.is_dir() else [path]:
            if member.is_symlink():
                raise ValueError("symlink in ABI input")
            if member.is_file():
                result[str(member.relative_to(directory))] = sha(member)
    return result


def checks():
    for path, digest in LOCKS.items():
        ordinary(path)
        if sha(path) != digest:
            raise ValueError("input lock rejected: " + str(path))
    if command(["git", "-C", KERNEL, "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("original kernel commit changed")
    if command(["git", "-C", KERNEL, "status", "--porcelain"]):
        raise ValueError("original kernel is not clean")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("kbuild-review-object-" + args.version)
    if output.exists() or output.is_symlink():
        raise ValueError("object output exists")
    source_dir = args.source_dir.resolve()
    if source_dir.parent != HERE:
        raise ValueError("candidate must be in owned output directory")
    checks()
    manifest = json.loads((source_dir / "manifest.json").read_text())
    if sha(source_dir / SOURCE) != manifest["source_sha256"]:
        raise ValueError("candidate lock failed")
    config = (ABI / ".config").read_text().splitlines()
    required = ["CONFIG_SND_SOC_ROCKCHIP_I2S_TDM=y", "CONFIG_SND_SOC_GENERIC_DMAENGINE_PCM=y", "CONFIG_SND_DMAENGINE_PCM=y", "CONFIG_PL330_DMA=y", "CONFIG_PM=y", "CONFIG_PM_SLEEP=y", "CONFIG_NO_GKI=y", "# CONFIG_SND_SOC_ROCKCHIP_I2S_TDM_MULTI_LANES is not set"]
    if any(token not in config for token in required):
        raise ValueError("actual config profile differs")
    before = inventory(ABI)
    compiler = command(["aarch64-linux-gnu-gcc", "--version"]).splitlines()[0]
    if compiler != "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0":
        raise ValueError("compiler differs from original Image")
    output.mkdir()
    shutil.copy2(Path(__file__), output / "build-object.py")
    shutil.copy2(DTB, output / "audio.dtb")
    dt_tool = ABI / "scripts/dtc/dtc"
    ordinary(dt_tool)
    dt_result = subprocess.run([str(dt_tool), "-I", "dtb", "-O", "dts", str(DTB)], capture_output=True, text=True, check=True)
    (output / "audio.dts").write_text(dt_result.stdout)
    (output / "dtc.stderr").write_text(dt_result.stderr)
    shadow = output / "kernel-abi"
    shadow.mkdir()
    for relative in COPY_DIRS:
        shutil.copytree(ABI / relative, shadow / relative)
    for relative in COPY_FILES:
        shutil.copy2(ABI / relative, shadow / relative)
    if inventory(shadow) != before:
        raise ValueError("ABI copy changed bytes")
    overlay = output / "include-overlay"
    header = overlay / "arch/arm64/include/asm/cache.h"
    header.parent.mkdir(parents=True)
    shutil.copy2(KERNEL / "arch/arm64/include/asm/cache.h", header)
    patch = subprocess.run(["patch", "--batch", "-p1", "-d", str(overlay), "-i", str(CACHE_PATCH)], capture_output=True, text=True)
    (output / "cache-overlay.txt").write_text(patch.stdout + patch.stderr)
    if patch.returncode:
        raise ValueError("locked cache include overlay failed")
    module_dir = output / "objects"
    module_dir.mkdir()
    shutil.copy2(source_dir / SOURCE, module_dir / "rockchip_i2s_tdm.c")
    headers = {}
    for name in ["rockchip_i2s_tdm.h", "rockchip_dlp.h"]:
        path = KERNEL / "sound/soc/rockchip" / name
        ordinary(path)
        shutil.copy2(path, module_dir / name)
        headers[name] = sha(path)
    (module_dir / "Makefile").write_text("# Object-only ABI validation; no module or Image.\nobj-m += rockchip_i2s_tdm.o\n")
    include_paths = [overlay / "arch/arm64/include", KERNEL / "arch/arm64/include", shadow / "arch/arm64/include/generated", KERNEL / "include", shadow / "include", KERNEL / "arch/arm64/include/uapi", shadow / "arch/arm64/include/generated/uapi", KERNEL / "include/uapi", shadow / "include/generated/uapi"]
    include = " ".join("-I" + str(p) for p in include_paths) + " -include " + str(KERNEL / "include/linux/kconfig.h")
    argv = ["make", "-C", str(shadow), "M=" + str(module_dir), "ARCH=arm64", "CROSS_COMPILE=aarch64-linux-gnu-", "LINUXINCLUDE=" + include, "V=1", "-j2", "rockchip_i2s_tdm.o"]
    built = subprocess.run(argv, capture_output=True, text=True)
    (output / "build.stdout").write_text(built.stdout)
    (output / "build.stderr").write_text(built.stderr)
    (output / "build-argv.json").write_text(json.dumps(argv, indent=2) + "\n")
    checks()
    if inventory(ABI) != before:
        raise ValueError("original ABI changed during object compile")
    record = {"exit_code": built.returncode, "source_commit": COMMIT, "source_sha256": manifest["source_sha256"], "original_source_clean": True, "original_abi_unchanged": True, "abi_metadata_sha256": before, "inputs_sha256": {str(p.relative_to(ROOT)): d for p, d in LOCKS.items()}, "headers_sha256": headers, "copied_config_sha256": sha(shadow / ".config"), "compiler": compiler, "build_argv": argv, "required_actual_config": required, "published": False, "deployable": False, "board_tested": False, "full_image_built": False, "object_only": True}
    if not built.returncode:
        obj = module_dir / "rockchip_i2s_tdm.o"
        data = obj.read_bytes()
        if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", data, 16) != (1, 183):
            raise ValueError("object must be ELF64 LE AArch64 ET_REL")
        (output / "object-readelf.txt").write_text(command(["aarch64-linux-gnu-readelf", "-h", "-S", obj]) + "\n")
        record["object_sha256"] = sha(obj)
        record["object_bytes"] = len(data)
        record["kbuild_command_sha256"] = sha(module_dir / ".rockchip_i2s_tdm.o.cmd")
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ["exit_code", "source_sha256", "original_source_clean", "original_abi_unchanged", "published", "deployable", "board_tested"]} | {"result": str(output / "result.json"), "object_sha256": record.get("object_sha256")}))
    return int(built.returncode != 0)


if __name__ == "__main__":
    raise SystemExit(main())
