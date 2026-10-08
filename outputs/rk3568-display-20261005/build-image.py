#!/usr/bin/env python3
"""Build display Image in a private locked checkout; leave tested Image intact."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ORIGINAL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
BOARD = ROOT / "platforms/rk3568/boards/aiot-3568pq"
CONFIG_SHA = "1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912"
IMAGE = ROOT / "outputs/rk3568-rcu-reset-20261004/Image"
IMAGE_SHA = "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457"
PANEL = "drivers/gpu/drm/panel/panel-simple.c"
PATCHES = ["0001-arm64-cache-kasan-include.patch",
           "0002-rk817-feedback-diagnostic.patch",
           "0003-printk-rcu-flush-context.patch",
           "0008-panel-simple-init-errors.patch"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, env=None):
    return subprocess.check_output(argv, text=True, env=env).strip()


def original_lock():
    if command(["git", "-C", str(ORIGINAL), "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("Original source commit changed")
    if command(["git", "-C", str(ORIGINAL), "status", "--porcelain"]):
        raise ValueError("Original source is not clean")
    if sha(IMAGE) != IMAGE_SHA:
        raise ValueError("Previously tested Image changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--panel-version", required=True)
    parser.add_argument("--tests-directory", required=True)
    parser.add_argument("--use-prepared", action="store_true",
                        help="Use a clean private checkout and config prepared earlier")
    args = parser.parse_args()
    for value in [args.revision, args.panel_version]:
        if not re.fullmatch(r"v[1-9][0-9]*", value):
            parser.error("versions must be vN")
    if not re.fullmatch(r"panel-tests-realhost-green-v[1-9][0-9]*", args.tests_directory):
        parser.error("tests-directory must name a real-host green evidence directory")
    original_lock()
    output = HERE / "build" / ("image-" + args.revision)
    source = ROOT / ".deps/kernel-source" / ("aiot-3568pq-display-" + args.revision)
    build = ROOT / ".deps/kernel" / ("aiot-3568pq-display-" + args.revision)
    if output.exists():
        raise ValueError("Refusing to overwrite Image evidence")
    if not args.use_prepared:
        if source.exists() or build.exists():
            raise ValueError("Private source or build directory already exists")
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--shared", "--no-checkout", str(ORIGINAL), str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", COMMIT], check=True)
        subprocess.run(["python3", str(ROOT / "scripts/prepare-linux-config.py"),
                        "--candidate", str(BOARD / "firstboot-candidate.json"),
                        "--source", str(source), "--output", str(build)], check=True)
    if source.is_symlink() or build.is_symlink() or source.resolve() == ORIGINAL.resolve():
        raise ValueError("Private paths must be independent")
    if command(["git", "-C", str(source), "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("Private source commit changed")
    if command(["git", "-C", str(source), "status", "--porcelain"]):
        raise ValueError("Private source already modified")
    if sha(build / ".config") != CONFIG_SHA:
        raise ValueError("Private config differs from tested Image")
    if (build / "arch/arm64/boot/Image").exists():
        raise ValueError("Private build already contains Image")
    candidate = HERE / ("panel-source-" + args.panel_version)
    tested = HERE / args.tests_directory / "result.json"
    manifest = json.loads((candidate / "manifest.json").read_text())
    checks = json.loads(tested.read_text())
    patch = BOARD / "patches" / PATCHES[-1]
    if manifest["source_commit"] != COMMIT or manifest["patch_sha256"] != sha(patch):
        raise ValueError("Panel candidate and published patch differ")
    if not checks["passed"] or checks["source_sha256"] != manifest["source_sha256"]:
        raise ValueError("Panel candidate has no passing function test")
    if checks["source_sha256"] != sha(candidate / PANEL):
        raise ValueError("Panel tested source changed")
    for name, digest in checks["harness_sha256"].items():
        if sha(HERE / name) != digest:
            raise ValueError("Panel harness changed after passing tests")
    for name, digest in checks["dsi_chain"]["inputs_sha256"].items():
        if sha(ORIGINAL / name) != digest:
            raise ValueError("Tested real DSI call chain changed")
    if sha(Path(checks["board_fixture"]["dts"])) != checks["board_fixture"]["dts_sha256"]:
        raise ValueError("Tested board init fixture changed")
    for result in checks["runs"].values():
        if result["compile"]["returncode"] or result["execution"]["returncode"] or result["tests"]["failed"]:
            raise ValueError("Panel test execution failed")
    output.mkdir(parents=True)
    env = dict(os.environ)
    env["PATH"] = str(ROOT / ".deps/host-tools/bin") + ":" + env["PATH"]
    compiler = command(["aarch64-linux-gnu-gcc", "--version"], env).splitlines()[0]
    if compiler != "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0":
        raise ValueError("Compiler differs from tested Image")
    applied = {}
    for index, name in enumerate(PATCHES, 1):
        path = BOARD / "patches" / name
        result = subprocess.run(["git", "-C", str(source), "apply", "--check", str(path)],
                                capture_output=True, text=True)
        (output / ("patch-check-" + str(index) + ".txt")).write_text(result.stdout + result.stderr)
        result.check_returncode()
        subprocess.run(["git", "-C", str(source), "apply", str(path)], check=True)
        applied[name] = sha(path)
    if sha(source / PANEL) != manifest["source_sha256"]:
        raise ValueError("Replayed panel source differs from tested source")
    make = ["make", "-C", str(source), "O=" + str(build), "ARCH=arm64",
            "CROSS_COMPILE=aarch64-linux-gnu-", "-j8", "Image"]
    plan = {"source_commit": COMMIT, "compiler": compiler, "patch_sha256": applied,
            "source": str(source), "build": str(build), "config_sha256": CONFIG_SHA,
            "panel_test_sha256": sha(tested), "panel_source_sha256": sha(source / PANEL),
            "build_argv": make, "previous_image_sha256": IMAGE_SHA,
            "board_tested": False, "deployable": False}
    (output / "inputs.json").write_text(json.dumps(plan, indent=2) + "\n")
    print("DISPLAY_IMAGE_BUILD_STARTED " + str(output), flush=True)
    with (output / "build.txt").open("w") as stream:
        result = subprocess.run(make, stdout=stream, stderr=subprocess.STDOUT, env=env)
    original_lock()
    if result.returncode:
        raise ValueError("Image build failed; see build.txt")
    if sha(build / ".config") != CONFIG_SHA:
        raise ValueError("Build changed config")
    # Image-only Kbuild emits vmlinux.symvers. Module.symvers additionally needs
    # a modules build and must not be invented or borrowed from another Image.
    for name in ["arch/arm64/boot/Image", ".config", "vmlinux.symvers"]:
        target = output / ("kernel.config" if name == ".config" else Path(name).name)
        shutil.copy2(build / name, target)
    data = (output / "Image").read_bytes()
    if data[0x38:0x3c] != b"ARM\x64":
        raise ValueError("Image is not ARM64")
    plan.update({"image_sha256": sha(output / "Image"), "image_bytes": len(data),
                 "image_crc32": "%08x" % zlib.crc32(data),
                 "text_offset": int.from_bytes(data[8:16], "little"),
                 "image_memory_bytes": int.from_bytes(data[16:24], "little"),
                 "vmlinux_symvers_sha256": sha(build / "vmlinux.symvers"),
                 "kernel_release": (build / "include/config/kernel.release").read_text().strip(),
                 "original_source_clean_after_build": True, "build_exit_code": result.returncode})
    (output / "manifest.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps({key: plan[key] for key in ["image_sha256", "image_bytes", "image_crc32",
                                               "image_memory_bytes", "kernel_release"]}))


if __name__ == "__main__":
    main()
