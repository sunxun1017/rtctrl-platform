#!/usr/bin/env python3
"""Finish v1 evidence after Image-only symbol-table naming was corrected."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("display_build", HERE / "build-image.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def main():
    base.original_lock()
    output = HERE / "build/image-v1"
    if (output / "manifest.json").exists():
        raise ValueError("Refusing existing completed manifest")
    plan = json.loads((output / "inputs.json").read_text())
    source, build = Path(plan["source"]), Path(plan["build"])
    if base.sha(build / ".config") != plan["config_sha256"]:
        raise ValueError("Config changed")
    changes = base.command(["git", "-C", str(source), "diff", "--name-only"]).splitlines()
    expected = ["arch/arm64/include/asm/cache.h", "drivers/mfd/rk808.c",
                "kernel/printk/printk.c", base.PANEL]
    if set(changes) != set(expected):
        raise ValueError("Private source has unexpected changes")
    with tempfile.TemporaryDirectory() as folder:
        replay = Path(folder)
        for name in expected:
            target = replay / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base.ORIGINAL / name, target)
        for name, digest in plan["patch_sha256"].items():
            patch = base.BOARD / "patches" / name
            if base.sha(patch) != digest:
                raise ValueError("Published patch changed")
            subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-d", folder,
                            "-i", str(patch)], check=True, capture_output=True)
        for name in expected:
            if base.sha(replay / name) != base.sha(source / name):
                raise ValueError("Private source differs from fresh patch replay")
    # This incremental make rechecks completion and records its actual exit code;
    # it is not a claim that the failed packaging attempt had a complete manifest.
    with (output / "finalize-build.txt").open("x") as stream:
        result = subprocess.run(plan["build_argv"], stdout=stream, stderr=subprocess.STDOUT)
    result.check_returncode()
    base.original_lock()
    if base.sha(build / ".config") != base.CONFIG_SHA:
        raise ValueError("Build changed config")
    for name in ["arch/arm64/boot/Image", ".config", "vmlinux.symvers"]:
        target = output / ("kernel.config" if name == ".config" else Path(name).name)
        if target.exists() and base.sha(target) != base.sha(build / name):
            raise ValueError("Previously copied artifact differs")
        if not target.exists():
            shutil.copy2(build / name, target)
    data = (output / "Image").read_bytes()
    if data[0x38:0x3c] != b"ARM\x64":
        raise ValueError("Image is not ARM64")
    plan.update({"image_sha256": base.sha(output / "Image"), "image_bytes": len(data),
                 "image_crc32": "%08x" % zlib.crc32(data),
                 "text_offset": int.from_bytes(data[8:16], "little"),
                 "image_memory_bytes": int.from_bytes(data[16:24], "little"),
                 "vmlinux_symvers_sha256": base.sha(build / "vmlinux.symvers"),
                 "kernel_release": (build / "include/config/kernel.release").read_text().strip(),
                 "original_source_clean_after_build": True, "fresh_patch_replay_matches_private_source": True,
                 "build_exit_code": result.returncode,
                 "packaging_repair": "Image build passed; Module.symvers absent in Image-only build. Use actual vmlinux.symvers after rechecking make.",
                 "source_diff_sha256": __import__("hashlib").sha256(subprocess.check_output(
                     ["git", "-C", str(source), "diff", "--binary"])).hexdigest()})
    (output / "manifest.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps({key: plan[key] for key in ["image_sha256", "image_bytes", "image_crc32",
                                               "image_memory_bytes", "kernel_release"]}))


if __name__ == "__main__":
    main()
