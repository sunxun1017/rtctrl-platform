#!/usr/bin/env python3
"""Build PCM fixes against private copies of the exact, already tested Image ABI."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "outputs/rk3568-audio-20261005"
spec = importlib.util.spec_from_file_location("codec_build", OLD / "build-codec.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
PATCH = base.PATCHES / "0007-rk817-pcm-configuration-errors.patch"
SOURCE = "sound/soc/codecs/rk817_codec.c"
HEADER = "sound/soc/codecs/rk817_codec.h"

def validate_tests(source):
    paths = [HERE / "runtime-tests-green-v1/result.json", HERE / "runtime-tests-green-v2/result.json"]
    for path in paths:
        record = json.loads(path.read_text())
        if record["total"] != 246 or record["passed"] != 246 or record["exit_code"]:
            raise ValueError("Runtime fault tests must pass")
        if record["source_sha256"] != base.sha(source):
            raise ValueError("Runtime tested source differs")
        for name, digest in record["test_inputs"].items():
            if base.sha(HERE / name) != digest:
                raise ValueError("Runtime test input changed")
    path = OLD / "driver-tests-green-v7/result.json"
    probe = json.loads(path.read_text())
    if probe["total"] != 73 or probe["passed"] != 73 or probe["exit_code"]:
        raise ValueError("Registration regression must pass on this candidate")
    if probe["source_sha256"].get(str(source.relative_to(ROOT))) != base.sha(source):
        raise ValueError("Registration tested source differs")
    for name, digest in probe["test_input_sha256"].items():
        if base.sha(OLD / name) != digest:
            raise ValueError("Registration test input changed")
    return paths + [path]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    output = HERE / ("driver-modules-" + args.version)
    base.new_output(output)
    base.check_locks()
    candidate = HERE / "driver-source-v1"
    record = json.loads((candidate / "manifest.json").read_text())
    if record["patch_sha256"] != base.sha(PATCH):
        raise ValueError("Patch differs from candidate")
    for relative, digest in record["sources"].items():
        if relative not in [SOURCE, HEADER] or base.sha(candidate / relative) != digest:
            raise ValueError("Candidate source differs")
    tests = validate_tests(candidate / SOURCE)
    compiler = base.command(["aarch64-linux-gnu-gcc", "--version"]).splitlines()[0]
    if compiler != "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0":
        raise ValueError("Compiler differs from Image")
    before = base.inventory(base.ABI)
    output.mkdir()
    replay = output / "patch-replay"
    replay.mkdir()
    for relative in [SOURCE, HEADER]:
        target = replay / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base.KERNEL / relative, target)
    for index, patch in enumerate([base.PATCH, PATCH], 1):
        result = subprocess.run(["patch", "--batch", "-p1", "-d", str(replay), "-i", str(patch)],
                                capture_output=True, text=True)
        (output / ("patch-" + str(index) + ".txt")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError("Published patch replay failed")
    for relative in [SOURCE, HEADER]:
        if base.sha(replay / relative) != base.sha(candidate / relative):
            raise ValueError("Public patches differ from candidate")
    shadow = output / "kernel-abi"
    shadow.mkdir()
    for relative in base.COPY_DIRS:
        shutil.copytree(base.ABI / relative, shadow / relative)
    for relative in base.COPY_FILES:
        shutil.copy2(base.ABI / relative, shadow / relative)
    if base.inventory(shadow) != before:
        raise ValueError("Copied ABI differs")
    overlay = output / "include-overlay"
    header = overlay / "arch/arm64/include/asm/cache.h"
    header.parent.mkdir(parents=True)
    shutil.copy2(base.KERNEL / "arch/arm64/include/asm/cache.h", header)
    result = subprocess.run(["patch", "--batch", "-p1", "-d", str(overlay), "-i",
                             str(base.PATCHES / "0001-arm64-cache-kasan-include.patch")],
                            capture_output=True, text=True)
    (output / "cache-patch.txt").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError("Cache overlay failed")
    modules = output / "modules"
    modules.mkdir()
    for relative in [SOURCE, HEADER]:
        shutil.copy2(candidate / relative, modules / Path(relative).name)
    (modules / "Makefile").write_text("obj-m += snd-soc-rk817.o\nsnd-soc-rk817-objs := rk817_codec.o\n")
    include_paths = [overlay / "arch/arm64/include", base.KERNEL / "arch/arm64/include",
                     shadow / "arch/arm64/include/generated", base.KERNEL / "include", shadow / "include",
                     base.KERNEL / "arch/arm64/include/uapi", shadow / "arch/arm64/include/generated/uapi",
                     base.KERNEL / "include/uapi", shadow / "include/generated/uapi"]
    includes = " ".join("-I" + str(path) for path in include_paths)
    includes += " -include " + str(base.KERNEL / "include/linux/kconfig.h")
    argv = ["make", "-C", str(shadow), "M=" + str(modules), "ARCH=arm64",
            "CROSS_COMPILE=aarch64-linux-gnu-", "LINUXINCLUDE=" + includes, "V=1", "-j2", "modules"]
    result = subprocess.run(argv, capture_output=True, text=True)
    (output / "build.txt").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError("Codec build failed; see build.txt")
    base.check_locks()
    if base.inventory(base.ABI) != before:
        raise ValueError("Original Image ABI changed")
    module = modules / "snd-soc-rk817.ko"
    audit = base.audit_module(module, output, base.symbols(shadow / "Module.symvers"))
    own = base.symbols(modules / "Module.symvers")
    if own:
        raise ValueError("Unexpected module exports")
    manifest = {"source_commit": base.COMMIT, "source_clean": True, "compiler": compiler,
                "image_sha256": base.sha(base.IMAGE), "image_abi_unchanged": True,
                "config_sha256": base.sha(base.ABI / ".config"), "build_argv": argv,
                "abi_inventory": before, "candidate_manifest": record,
                "real_function_tests": {str(p.relative_to(ROOT)): base.sha(p) for p in tests},
                "patch_replay_matches_candidate": True, "module": audit, "board_tested": False,
                "pcm_data_transfer_tested": False, "full_runtime_path_fix": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"sha256": audit["sha256"], "bytes": audit["bytes"], "imports": len(audit["imports"])}))

if __name__ == "__main__":
    main()
