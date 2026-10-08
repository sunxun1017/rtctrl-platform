#!/usr/bin/env python3
"""Produce hash-bound RAM boot/staging sessions without communicating with hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--helper-sha256", required=True)
    args = parser.parse_args()
    if len(args.helper_sha256) != 64 or any(c not in "0123456789abcdef" for c in args.helper_sha256):
        raise ValueError("Need reviewed helper fingerprint")
    staging = HERE / "build/staging-v1"
    if staging.exists() or staging.is_symlink() or staging.parent.is_symlink():
        raise ValueError("Refusing existing/symlink staging")
    files = {
        "cap1188-spi.dtb": (HERE / "build/dtb-v3/cap1188-spi.dtb", "fdc469fc60abbb203bfa585232dfe9f0501c87340c534401183263ebc866acd4"),
        "cap1188-inspect": (HERE / "build/inspect-v1/cap1188-inspect", args.helper_sha256),
    }
    for name in ["linux-enumeration.sh", "linux-identity.sh", "linux-return-guard.sh"]:
        files[name] = (HERE / name, None)
    hashes = {}
    for name, (path, expected) in files.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Need ordinary input: " + str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected and digest != expected:
            raise ValueError("Pinned input changed: " + name)
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

    old = ROOT / "outputs/rk3568-motor-alignment-20261004"
    load = json.loads((old / "load-ram.json").read_text())
    data = (staging / "cap1188-spi.dtb").read_bytes()
    load[2] = step("ext4load mmc 0:c 3000000 /rtctrl-cap1188-20261004/cap1188-spi.dtb",
                   str(len(data)) + " bytes read", 4)
    load[3] = step(f"crc32 3000000 {len(data):x}", f"==> {zlib.crc32(data):08x}")
    write("load-ram.json", load)
    write("boot-ram.json", json.loads((old / "boot-ram.json").read_text()))
    stage_data = (HERE / "linux-stage.sh").read_bytes()
    stage_steps = []
    for offset in range(0, len(stage_data), 96):
        encoded = "".join("\\0" + f"{b:03o}" for b in stage_data[offset:offset + 96])
        stage_steps.append(step(f"printf '%b' '{encoded}' {'>' if offset == 0 else '>>'} /tmp/cap-stage.sh", wait=0.05))
    stage_sha = hashlib.sha256(stage_data).hexdigest()
    stage_steps.append(step("test \"$(sha256sum /tmp/cap-stage.sh)\" = '" + stage_sha +
                            "  /tmp/cap-stage.sh' && sh /tmp/cap-stage.sh",
                            r"(?m)^CAP_INPUTS_IN_RAM_CACHE_RELEASED\r?$", 5))
    write("linux-stage.json", stage_steps)
    write("linux-enumeration.json", [step("sh /tmp/cap1188/linux-enumeration.sh",
                                        r"(?m)^CAP_SPI_ENUMERATION_COMPLETE_NO_DEVICE_OPEN\r?$", 3)])
    write("linux-identity.json", [step("sh /tmp/cap1188/linux-identity.sh",
                                     r"(?m)^CAP_SPI_DIAGNOSTIC_COMPLETE_NO_INPUT_DRIVER\r?$", 3)])
    write("return-android.json", [step("sh /tmp/cap1188/linux-return-guard.sh",
                                     r"(?m)^CAP_RAM_ONLY_RESET_READY\r?$", 3),
                                  step("dmesg", wait=2), step("echo b > /proc/sysrq-trigger", wait=40)])
    write("runtime-manifest.json", {"files": hashes, "stage_script_sha256": stage_sha,
                                   "transport": "shell printf percent-b octal; readback SHA before execution",
                                   "dtb_bytes": len(data), "dtb_crc32": f"{zlib.crc32(data):08x}",
                                   "board_tested": False})
    for name in ["serial-console.ps1", "inspect-uboot.ps1"]:
        target = HERE / "private" / name
        if target.exists():
            raise ValueError("Refusing existing private helper")
        shutil.copyfile(old / "private" / name, target)
    print(json.dumps({"status": "CAP_STAGING_AND_SESSIONS_PREPARED", "files": hashes,
                      "dtb_bytes": len(data), "dtb_crc32": f"{zlib.crc32(data):08x}"}, indent=2))


if __name__ == "__main__":
    main()
