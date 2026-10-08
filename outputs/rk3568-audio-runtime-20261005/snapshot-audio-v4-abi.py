#!/usr/bin/env python3
"""Snapshot current generated ABI just after the completed root Image build."""
import hashlib
import json
from pathlib import Path
import shutil
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILD = ROOT / ".deps/kernel/aiot-3568pq-audio-v4"
IMAGE = HERE / "build/integration-v4"
OUT = HERE / "build/root-image-v4-abi-v1"
SELECTED = [".config", "Module.symvers", "vmlinux.symvers", "Makefile",
            "include", "arch/arm64/include", "scripts"]
MANIFEST_SHA = "8df525843cac41fd0e272351bc41d0e573c25570cfed7e60f1990b9fe97aa33a"


def ordinary(path, directory=False):
    if not path.is_relative_to(ROOT) or ".." in path.parts:
        raise ValueError("Escaped input")
    check = stat.S_ISDIR if directory else stat.S_ISREG
    if not check(path.lstat().st_mode):
        raise ValueError("Nonordinary input: " + str(path))
    for ancestor in path.parents:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError("Nonordinary ancestry")
        if ancestor == ROOT:
            break


def sha(path):
    ordinary(path)
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inventory():
    result = {}
    for selection in SELECTED:
        base = BUILD / selection
        paths = [base]
        if base.is_dir():
            ordinary(base, directory=True)
            paths = sorted(base.rglob("*"))
        for path in paths:
            if stat.S_ISDIR(path.lstat().st_mode):
                ordinary(path, directory=True)
                continue
            ordinary(path)
            result[path.relative_to(BUILD).as_posix()] = {
                "sha256": sha(path), "bytes": path.stat().st_size,
                "mode": stat.S_IMODE(path.stat().st_mode)}
    return result


def main():
    if OUT.exists() or OUT.is_symlink():
        raise ValueError("Fresh snapshot required")
    if sha(IMAGE / "manifest.json") != MANIFEST_SHA:
        raise ValueError("Actual completed Image changed")
    image = json.loads((IMAGE / "manifest.json").read_bytes())
    if image["build_exit_code"] != 0 or sha(IMAGE / "Image") != image["image_sha256"]:
        raise ValueError("Completed Image identity failed")
    locks = {".config": image["config_sha256"],
             "Module.symvers": image["module_symvers_sha256"],
             "vmlinux.symvers": image["vmlinux_symvers_sha256"],
             "arch/arm64/boot/Image": image["image_sha256"]}
    for relative, digest in locks.items():
        if sha(BUILD / relative) != digest:
            raise ValueError("Actual Image ABI identity failed")
    before = inventory()
    OUT.mkdir()
    for relative, entry in before.items():
        target = OUT / "snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BUILD / relative, target)
        if sha(target) != entry["sha256"] or target.stat().st_size != entry["bytes"] or stat.S_IMODE(target.stat().st_mode) != entry["mode"]:
            raise ValueError("Snapshot readback differs")
    if inventory() != before:
        raise ValueError("Actual generated ABI changed during snapshot")
    for relative, digest in locks.items():
        if sha(BUILD / relative) != digest:
            raise ValueError("Actual Image inputs changed after snapshot")
    inventory_path = OUT / "inventory.json"
    inventory_path.write_bytes((json.dumps({"files": before, "selections": SELECTED}, indent=2) + "\n").encode())
    result = {"root_current_generated_ABI_snapshot_completed": True,
              "image_manifest_sha256": MANIFEST_SHA, "image_sha256": image["image_sha256"],
              "inventory_sha256": sha(inventory_path), "ordinary_files": len(before),
              "actual_BUILD_selection_before_after_equal": True,
              "copied_bytes_sizes_modes_equal": True, "snapshot_tool_sha256": sha(Path(__file__)),
              "scope": "Fresh current actual BUILD generated inputs after Image completion and before external codec build",
              "generated_inventory_was_signed_at_Image_compile_time": False,
              "Image_recompiled_during_snapshot": False, "module_built": False,
              "hardware_operated": False}
    (OUT / "receipt.json").write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps({"ordinary_files": len(before), "inventory_sha256": sha(inventory_path),
                      "receipt_sha256": sha(OUT / "receipt.json")}))


if __name__ == "__main__":
    main()
