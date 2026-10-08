#!/usr/bin/env python3
"""Produce reviewed hash-bound sessions; never communicate with the board."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True, type=Path)
    parser.add_argument("--module-sha256", required=True)
    parser.add_argument("--helper", required=True, type=Path)
    parser.add_argument("--helper-sha256", required=True)
    args = parser.parse_args()
    staging = HERE / "build/staging-v1"
    if staging.exists() or staging.is_symlink() or staging.parent.is_symlink():
        raise ValueError("Refusing existing or symlink staging")
    files = {
        "audio.dtb": (HERE / "build/dtb-v3/audio.dtb", "9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478"),
        "snd-soc-rk817.ko": (args.module, args.module_sha256),
        "alsa-inspect": (args.helper, args.helper_sha256),
        "linux-interface.sh": (HERE / "linux-interface.sh", None),
        "linux-return-guard.sh": (HERE / "linux-return-guard.sh", None),
    }
    hashes = {}
    for name, (path, expected) in files.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Need ordinary input: " + str(path))
        digest = sha(path)
        if expected and (len(expected) != 64 or digest != expected):
            raise ValueError("Reviewed fingerprint mismatch: " + name)
        hashes[name] = digest
    staging.mkdir()
    for name, (path, _) in files.items():
        shutil.copyfile(path, staging / name)
    (staging / "upload.sha256").write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()))
    shutil.copyfile(HERE / "prepare-android.sh", staging / "prepare-android.sh")

    def step(command, expect=None, wait=1):
        item = {"command": command, "wait": wait}
        if expect:
            item["expect"] = expect
        return item

    def write(name, value):
        with (HERE / name).open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")

    old = HERE.parent / "rk3568-cap1188-20261004"
    load = json.loads((old / "load-ram.json").read_text())
    data = (staging / "audio.dtb").read_bytes()
    load[2] = step("ext4load mmc 0:c 3000000 /rtctrl-audio-20261005/audio.dtb", str(len(data)) + " bytes read", 4)
    load[3] = step(f"crc32 3000000 {len(data):x}", f"==> {zlib.crc32(data):08x}")
    write("load-ram.json", load)
    write("boot-ram.json", json.loads((old / "boot-ram.json").read_text()))
    stage_data = (HERE / "linux-stage.sh").read_bytes()
    steps = []
    for offset in range(0, len(stage_data), 96):
        encoded = "".join("\\0" + f"{byte:03o}" for byte in stage_data[offset:offset + 96])
        steps.append(step(f"printf '%b' '{encoded}' {'>' if offset == 0 else '>>'} /tmp/audio-stage.sh", wait=0.05))
    stage_sha = hashlib.sha256(stage_data).hexdigest()
    steps.append(step("test \"$(sha256sum /tmp/audio-stage.sh)\" = '" + stage_sha +
                      "  /tmp/audio-stage.sh' && sh /tmp/audio-stage.sh",
                      r"(?m)^AUDIO_INPUTS_IN_RAM_CACHE_RELEASED\r?$", 5))
    write("linux-stage.json", steps)
    write("linux-interface.json", [step("sh /tmp/audio/linux-interface.sh",
                                        r"(?m)^AUDIO_METADATA_COMPLETE_NO_PCM_OPEN_NO_CONTROL_WRITE\r?$", 12)])
    write("return-android.json", [step("sh /tmp/audio/linux-return-guard.sh", r"(?m)^AUDIO_RAM_ONLY_RESET_READY\r?$", 3),
                                  step("dmesg", wait=2), step("echo b > /proc/sysrq-trigger", wait=40)])
    write("runtime-manifest.json", {"files": hashes, "stage_script_sha256": stage_sha,
                                   "transport": "octal shell printf; readback SHA before execution",
                                   "dtb_bytes": len(data), "dtb_crc32": f"{zlib.crc32(data):08x}",
                                   "board_tested": False})
    for name in ["serial-console.ps1", "inspect-uboot.ps1"]:
        target = HERE / "private" / name
        if target.exists():
            raise ValueError("Refusing existing private helper")
        shutil.copyfile(old / "private" / name, target)
    print(json.dumps({"status": "AUDIO_STAGING_AND_SESSIONS_PREPARED", "files": hashes,
                      "dtb_crc32": f"{zlib.crc32(data):08x}"}, indent=2))


if __name__ == "__main__":
    main()
