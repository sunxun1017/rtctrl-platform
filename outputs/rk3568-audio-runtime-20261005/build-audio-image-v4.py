#!/usr/bin/env python3
"""Build public 0001-0014 plus the reviewed private ASoC candidate offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ORIGINAL = ROOT / "third_party/linux-rk3588"
SOURCE = ROOT / ".deps/kernel-source/aiot-3568pq-audio-v4"
BUILD = ROOT / ".deps/kernel/aiot-3568pq-audio-v4"
OUT = HERE / "build/integration-v4"
BOARD = ROOT / "platforms/rk3568/boards/aiot-3568pq"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
CONFIG_SHA = "1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912"
CPU_SHA = "7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141"
CODEC_SHA = "72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64"
SOC_FILES = {
    "sound/soc/soc-pcm.c", "sound/soc/soc-component.c",
    "sound/soc/soc-compress.c", "sound/soc/generic/simple-card-utils.c"
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_bytes((json.dumps(data, indent=2) + "\n").encode())


def ordinary_directory(path):
    if not path.is_relative_to(ROOT) or ".." in path.parts:
        raise ValueError("Directory escaped repository")
    ancestor = path
    while True:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError("Nonordinary directory ancestry: " + str(ancestor))
        if ancestor == ROOT:
            break
        ancestor = ancestor.parent


def ordinary(relative):
    path = ROOT / relative
    if not path.is_relative_to(ROOT) or ".." in Path(relative).parts:
        raise ValueError("Input escaped repository")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Nonordinary input: " + str(relative))
    ordinary_directory(path.parent)
    return path


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def original_lock():
    ordinary_directory(ORIGINAL)
    if git(ORIGINAL, "rev-parse", "HEAD") != COMMIT or git(ORIGINAL, "status", "--porcelain"):
        raise ValueError("Original SDK changed")


def fresh_build(path):
    ordinary_directory(path)
    if set(item.name for item in path.iterdir()) != {".config"}:
        raise ValueError("Fresh build must contain only the initial .config")
    ordinary((path / ".config").relative_to(ROOT).as_posix())


def tracked_inventory(tree):
    listing = subprocess.check_output(["git", "-C", str(tree), "ls-files", "-s", "-z"])
    inventory = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, _, stage = metadata.decode().split()
        relative = name.decode()
        if stage != "0" or mode not in {"100644", "100755", "120000"}:
            raise ValueError("Unexpected tracked mode or stage")
        path = tree / relative
        info = path.lstat()
        if mode == "120000":
            if not stat.S_ISLNK(info.st_mode):
                raise ValueError("Tracked symlink changed type: " + relative)
            data = os.readlink(path).encode()
        else:
            if not stat.S_ISREG(info.st_mode) or bool(info.st_mode & 0o111) != (mode == "100755"):
                raise ValueError("Tracked file changed type or mode: " + relative)
            data = path.read_bytes()
        inventory[relative] = {"bytes": len(data), "mode": mode,
                               "sha256": hashlib.sha256(data).hexdigest()}
    return inventory


def recorded_run(argv, stem, env=None):
    # Keep real argv/exit and both diagnostic streams, including failed attempts.
    with (OUT / (stem + ".stdout")).open("wb") as stdout:
        with (OUT / (stem + ".stderr")).open("wb") as stderr:
            result = subprocess.run(argv, env=env, stdout=stdout, stderr=stderr)
    record = {"argv": argv, "exit": result.returncode,
              "stdout_sha256": sha(OUT / (stem + ".stdout")),
              "stderr_sha256": sha(OUT / (stem + ".stderr"))}
    write_json(OUT / (stem + ".command.json"), record)
    if result.returncode:
        raise ValueError("Failed " + stem + "; evidence retained")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-gate", required=True)
    args = parser.parse_args()
    original_lock()
    gate_path = ordinary(args.review_gate)
    gate = json.loads(gate_path.read_bytes())
    required_flags = ["accepted_for_offline_integration", "asoc_independent_review_completed",
                      "asoc_root_fresh_models_completed", "asoc_actual_Kbuild_completed",
                      "public_14_integration_review_completed"]
    if any(gate.get(flag) is not True for flag in required_flags):
        raise ValueError("Completed source/model/Kbuild and public review required")
    bound = gate["files_sha256"]
    if bound.get(Path(__file__).relative_to(ROOT).as_posix()) != sha(Path(__file__)):
        raise ValueError("This builder is not review-bound")

    def checked(relative):
        path = ordinary(relative)
        if bound.get(path.relative_to(ROOT).as_posix()) != sha(path):
            raise ValueError("Unbound or changed input: " + str(relative))
        return path

    for relative, expected in bound.items():
        if sha(ordinary(relative)) != expected:
            raise ValueError("Reviewed file changed: " + relative)
    source_manifest = json.loads(checked(gate["asoc_source_manifest"]).read_bytes())
    if set(source_manifest["files"]) != SOC_FILES:
        raise ValueError("Exactly four reviewed ASoC files required")
    if source_manifest["CPU_v12_modified"] or source_manifest["START_gates_modified"]:
        raise ValueError("CPU v12 and single START gates must remain")
    candidate_patch = checked(gate["asoc_patch"])
    if sha(candidate_patch) != source_manifest["patch_sha256"]:
        raise ValueError("Candidate patch differs from source review")
    for relative, entry in source_manifest["files"].items():
        path = checked(str(Path(gate["asoc_source_directory"]) / relative))
        if sha(path) != entry["sha256"]:
            raise ValueError("Reviewed candidate source changed")
    expected = json.loads(checked(gate["public_tracked_source_inventory"]).read_bytes())
    if len(expected) != 89423:
        raise ValueError("Complete actual-v3 source inventory required")
    for relative, entry in source_manifest["files"].items():
        if expected[relative]["sha256"] != entry["original_sha256"]:
            raise ValueError("Candidate baseline differs from public replay")

    if OUT.exists() or OUT.is_symlink():
        raise ValueError("Fresh integration output required")
    ordinary_directory(SOURCE)
    ordinary_directory(BUILD)
    ordinary_directory(OUT.parent)
    if git(SOURCE, "rev-parse", "HEAD") != COMMIT:
        raise ValueError("Prepared independent source required")
    if git(SOURCE, "status", "--porcelain"):
        raise ValueError("Prepared source or build already used")
    fresh_build(BUILD)
    if sha(BUILD / ".config") != CONFIG_SHA:
        raise ValueError("Original tested configuration required")
    env = dict(os.environ)
    env["PATH"] = str(ROOT / ".deps/host-tools/bin") + ":" + env["PATH"]
    compiler = subprocess.check_output(["aarch64-linux-gnu-gcc", "--version"], text=True, env=env).splitlines()[0]
    if compiler != "aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0":
        raise ValueError("Compiler differs from previous actual Image")
    patches = []
    for number in range(1, 15):
        matches = list((BOARD / "patches").glob(f"{number:04d}-*.patch"))
        if len(matches) != 1:
            raise ValueError("One public patch required for " + str(number))
        patches.append(checked(matches[0].relative_to(ROOT).as_posix()))

    OUT.mkdir(parents=True)
    applied = []
    for number, patch in enumerate([*patches, candidate_patch], 1):
        recorded_run(["git", "-C", str(SOURCE), "apply", "--check", str(patch)],
                     f"patch-{number:02d}-check")
        recorded_run(["git", "-C", str(SOURCE), "apply", str(patch)], f"patch-{number:02d}-apply")
        applied.append({"path": patch.relative_to(ROOT).as_posix(), "sha256": sha(patch)})
        if number == 14:
            public_inventory = tracked_inventory(SOURCE)
            write_json(OUT / "public-source-inventory.json", public_inventory)
            if public_inventory != expected:
                raise ValueError("Public replay differs from complete actual-v3 source")
    for relative, entry in source_manifest["files"].items():
        expected[relative] = {**expected[relative], "bytes": (SOURCE / relative).stat().st_size,
                              "sha256": entry["sha256"]}
    integrated = tracked_inventory(SOURCE)
    write_json(OUT / "integrated-source-inventory.json", integrated)
    if integrated != expected:
        raise ValueError("Integrated source differs from reviewed four-file delta")
    if sha(SOURCE / "sound/soc/rockchip/rockchip_i2s_tdm.c") != CPU_SHA:
        raise ValueError("CPU v12 changed")
    if sha(SOURCE / "sound/soc/codecs/rk817_codec.c") != CODEC_SHA:
        raise ValueError("Codec changed")
    argv = ["make", "-C", str(SOURCE), "O=" + str(BUILD), "ARCH=arm64",
            "CROSS_COMPILE=aarch64-linux-gnu-", "-j8", "Image", "modules"]
    inputs = {"source_commit": COMMIT, "source": SOURCE.relative_to(ROOT).as_posix(),
              "build": BUILD.relative_to(ROOT).as_posix(), "config_sha256": CONFIG_SHA,
              "compiler": compiler, "review_gate_sha256": sha(gate_path),
              "reviewed_files_sha256": bound, "patches": applied,
              "cpu_source_sha256": CPU_SHA, "codec_source_sha256": CODEC_SHA,
              "asoc_source_manifest_sha256": sha(checked(gate["asoc_source_manifest"])),
              "complete_public_source_verified": 89423, "asoc_changed_files": sorted(SOC_FILES),
              "public_source_inventory_sha256": sha(OUT / "public-source-inventory.json"),
              "integrated_source_inventory_sha256": sha(OUT / "integrated-source-inventory.json"),
              "build_argv": argv, "builder_sha256": sha(Path(__file__)),
              "battery_algorithm_enabled": False, "compressed_audio_enabled": False,
              "duplex_START_gates_relaxed": False, "board_tested": False, "deployed": False}
    write_json(OUT / "inputs.json", inputs)
    print("REVIEWED_AUDIO_V4_IMAGE_BUILD_STARTED", flush=True)
    build_record = recorded_run(argv, "build", env)
    original_lock()
    if sha(BUILD / ".config") != CONFIG_SHA:
        raise ValueError("Build changed configuration")
    for relative, expected_digest in bound.items():
        if sha(ordinary(relative)) != expected_digest:
            raise ValueError("Reviewed input changed during build")
    if tracked_inventory(SOURCE) != integrated:
        raise ValueError("Tracked source changed during build")
    for name in ["arch/arm64/boot/Image", ".config", "vmlinux.symvers", "Module.symvers"]:
        target = "kernel.config" if name == ".config" else Path(name).name
        shutil.copyfile(BUILD / name, OUT / target)
    data = (OUT / "Image").read_bytes()
    if data[0x38:0x3c] != b"ARM\x64":
        raise ValueError("Invalid ARM64 Image")
    manifest = {**inputs, "image_sha256": sha(OUT / "Image"), "image_bytes": len(data),
                "image_crc32": f"{zlib.crc32(data):08x}",
                "image_memory_bytes": int.from_bytes(data[16:24], "little"),
                "text_offset": int.from_bytes(data[8:16], "little"),
                "kernel_release": (BUILD / "include/config/kernel.release").read_text().strip(),
                "module_symvers_sha256": sha(OUT / "Module.symvers"),
                "vmlinux_symvers_sha256": sha(OUT / "vmlinux.symvers"),
                "original_clean": True, "build_exit_code": build_record["exit"]}
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in
                      ["image_sha256", "image_bytes", "image_crc32", "image_memory_bytes"]}), flush=True)


if __name__ == "__main__":
    main()
