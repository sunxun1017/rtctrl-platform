#!/usr/bin/env python3
"""Create new, hash-bound staging files and serial sessions; no board I/O."""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    staging = HERE / "build/staging-v1"
    if staging.exists() or staging.is_symlink() or staging.parent.is_symlink():
        raise ValueError("Refusing existing/symlink staging")
    staging.mkdir()
    files = {
        "accelerometer.dtb": (HERE / "build/dtb-v3/accelerometer.dtb", "e76139f3c9b978cbceb786ae26eb31c9618e32529f0dc9a8e4bbf1b778c77e12"),
        "sensor_dev.ko": (HERE / "driver-modules-v1/modules/sensor_dev.ko", "4dee08efa9a0214a089f0e615f8cc5f40035e3d330905d5ec05ab6de1a96d8a1"),
        "mxc6655xa.ko": (HERE / "driver-modules-v1/modules/mxc6655xa.ko", "f6b67fb459375e93b916b0df1a9b9e1996f90ede410b364bed63518c390099f9"),
        "sensor-inspect": (HERE / "build/inspect-v1/sensor-inspect", "9b706bd7e7acb4b704b2838e004dd71c1c3ebc9ea2cda59dd64d9d82f768cdfb"),
    }
    hashes = {}
    for name in ["linux-enumeration.sh", "linux-probe.sh", "linux-return-guard.sh"]:
        files[name] = (HERE / name, None)
    for name, (path, expected) in files.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Need ordinary input: " + str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected and digest != expected:
            raise ValueError("Pinned input changed: " + name)
        hashes[name] = digest
        shutil.copyfile(path, staging / name)
    (staging / "upload.sha256").write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()))
    shutil.copyfile(HERE / "prepare-android.sh", staging / "prepare-android.sh")
    def step(command, expect=None, wait=1):
        item = {"command": command, "wait": wait}
        if expect:
            item["expect"] = expect
        return item
    def write(name, steps):
        path = HERE / name
        with path.open("x") as stream:
            json.dump(steps, stream, indent=2)
            stream.write("\n")
    old = ROOT / "outputs/rk3568-motor-alignment-20261004"
    load = json.loads((old / "load-ram.json").read_text())
    data = (staging / "accelerometer.dtb").read_bytes()
    load[2] = step("ext4load mmc 0:c 3000000 /rtctrl-accelerometer-20261004/accelerometer.dtb",
                   str(len(data)) + " bytes read", 4)
    load[3] = step(f"crc32 3000000 {len(data):x}", f"==> {zlib.crc32(data):08x}")
    write("load-ram.json", load)
    write("boot-ram.json", json.loads((old / "boot-ram.json").read_text()))
    write("linux-stage.json", [step("sh -c " + shlex.quote((HERE / "linux-stage.sh").read_text()),
                                    r"(?m)^ACCEL_INPUTS_IN_RAM_CACHE_RELEASED\r?$", 5)])
    write("linux-enumeration.json", [step("sh /tmp/accel/linux-enumeration.sh",
                                          r"(?m)^LINUX_ACCEL_UNBOUND_NODE_AND_BUS_VERIFIED\r?$", 3)])
    write("linux-probe.json", [step("sh /tmp/accel/linux-probe.sh",
                                    r"(?m)^LINUX_ACCEL_DIAGNOSTIC_COMPLETE_NO_SAMPLING\r?$", 8)])
    write("return-android.json", [step("sh /tmp/accel/linux-return-guard.sh",
                                       r"(?m)^ACCEL_RAM_ONLY_RESET_READY_SENSOR_MODULES_RETAINED\r?$", 3),
                                   step("dmesg", wait=2), step("echo b > /proc/sysrq-trigger", wait=40)])
    for name in ["serial-console.ps1", "inspect-uboot.ps1"]:
        target = HERE / "private" / name
        if target.exists():
            raise ValueError("Refusing existing private helper")
        shutil.copyfile(old / "private" / name, target)
    print(json.dumps({"status": "ACCEL_STAGING_AND_SESSIONS_PREPARED", "files": hashes,
                      "dtb_bytes": len(data), "dtb_crc32": f"{zlib.crc32(data):08x}"}, indent=2))


if __name__ == "__main__":
    main()
