#!/usr/bin/env python3
"""Create immutable, checked host inputs and serial sessions, without communication."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "outputs/rk3568-audio-20261005"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.revision):
        parser.error("revision must be vN")
    suffix = "" if args.revision == "v1" else "-" + args.revision
    remote = "rtctrl-pcm-20261005" + suffix
    staging = HERE / "build" / ("staging-" + args.revision)
    if staging.exists() or staging.is_symlink():
        raise ValueError("Refuse existing staging")
    files = {
        "audio.dtb": (OLD / "build/dtb-v3/audio.dtb", "9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478"),
        "alsa-inspect": (OLD / "build/inspect-v4/alsa-inspect", "118cf99482cdd65acdfae8c5e85530a76bf60c90b0b0498e8f285223f862a945"),
        "snd-soc-rk817.ko": (HERE / "driver-modules-v1/modules/snd-soc-rk817.ko", "c9f761064980939431901d5da75383d048ff23eb686f3cc236733f658a2add3c"),
        "pcm-config": (HERE / "build/pcm-production-v1/pcm-config", None),
        "linux-interface.sh": (HERE / "linux-interface.sh", None),
        "linux-return-guard.sh": (HERE / "linux-return-guard.sh", None),
    }
    fingerprints = {}
    for name, (path, expected) in files.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError("Ordinary input required: " + str(path))
        fingerprints[name] = sha(path)
        if expected and expected != fingerprints[name]:
            raise ValueError("Reviewed input fingerprint mismatch: " + name)
    staging.mkdir(parents=True)
    for name, (path, _) in files.items():
        shutil.copyfile(path, staging / name)
    (staging / "upload.sha256").write_text("".join(digest + "  " + name + "\n" for name, digest in fingerprints.items()))
    (staging / "prepare-android.sh").write_text((HERE / "prepare-android.sh").read_text().replace("rtctrl-pcm-20261005", remote))
    stage_data = (HERE / "linux-stage.sh").read_text().replace("rtctrl-pcm-20261005", remote).encode()
    (staging / "linux-stage.sh").write_bytes(stage_data)
    stage_sha = hashlib.sha256(stage_data).hexdigest()

    def step(command, expect=None, wait=1):
        result = {"command": command, "wait": wait}
        if expect:
            result["expect"] = expect
        return result

    def write(name, value):
        name = name.replace(".json", suffix + ".json")
        with (HERE / name).open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")

    load = json.loads((OLD / "load-ram.json").read_text())
    load[2]["command"] = "ext4load mmc 0:c 3000000 /" + remote + "/audio.dtb"
    write("load-ram.json", load)
    write("boot-ram.json", json.loads((OLD / "boot-ram.json").read_text()))
    data = stage_data
    steps = []
    for offset in range(0, len(data), 96):
        encoded = "".join("\\0" + f"{byte:03o}" for byte in data[offset:offset + 96])
        redirect = ">" if offset == 0 else ">>"
        steps.append(step("printf '%b' '" + encoded + "' " + redirect + " /tmp/pcm-stage.sh", wait=0.05))
    steps.append(step("test \"$(sha256sum /tmp/pcm-stage.sh)\" = '" + stage_sha +
                      "  /tmp/pcm-stage.sh' && sh /tmp/pcm-stage.sh", r"(?m)^PCM_INPUTS_IN_RAM_CACHE_RELEASED\r?$", 5))
    write("linux-stage.json", steps)
    write("linux-interface.json", [step("sh /tmp/pcm/linux-interface.sh",
                                        r"(?m)^PCM_CONFIGURATION_COMPLETE_NO_PREPARE_NO_START_NO_AUDIO_FRAMES\r?$", 35)])
    write("return-android.json", [step("sh /tmp/pcm/linux-return-guard.sh", r"(?m)^PCM_RAM_ONLY_RESET_READY\r?$", 3),
                                  step("dmesg", wait=2), step("echo b > /proc/sysrq-trigger", wait=40)])
    write("runtime-manifest.json", {"files": fingerprints, "stage_script_sha256": stage_sha,
                                    "transport": "octal printf with readback SHA; host preparation only", "board_tested": False})
    print(json.dumps({"files": fingerprints, "staging": str(staging)}, indent=2))

if __name__ == "__main__":
    main()
