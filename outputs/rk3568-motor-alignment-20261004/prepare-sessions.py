#!/usr/bin/env python3
"""Record serial steps with sizes/CRC computed from pinned local inputs."""
import hashlib
import json
from pathlib import Path
import shlex
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def artifact(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Input SHA changed: " + str(path))
    return len(data), f"{len(data):x}", f"{zlib.crc32(data):08x}"


def write(name, steps):
    path = HERE / name
    with path.open("x") as stream:
        json.dump(steps, stream, indent=2)
        stream.write("\n")


def step(command, expect=None, wait=1):
    result = {"command": command, "wait": wait}
    if expect:
        result["expect"] = expect
    return result


def main():
    inputs = [
        (ROOT / "outputs/rk3568-rcu-reset-20261004/Image", "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457",
         "400000", "/rtctrl-source-wifi-20261004/Image"),
        (HERE / "uart.dtb", "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1",
         "3000000", "/rtctrl-motor-alignment-20261004/uart.dtb"),
        (HERE / "initramfs.cpio.gz", "f0965ceed549acab8d5bd87df8bb831bb06a95d08b5b7bf3c5582045933323ee",
         "4000000", "/rtctrl-motor-alignment-20261004/initramfs.cpio.gz"),
    ]
    load = []
    initrd_hex = None
    for path, expected, address, cache_path in inputs:
        size, size_hex, crc = artifact(path, expected)
        load.append(step(f"ext4load mmc 0:c {address} {cache_path}", f"{size} bytes read", 4))
        load.append(step(f"crc32 {address} {size_hex}", "==> " + crc))
        if address == "4000000":
            initrd_hex = size_hex
    load += [step("fdt addr 3000000"), step("fdt rsvmem print"), step("fdt print /reserved-memory", "no-map")]
    write("load-ram.json", load)
    boot = json.loads((ROOT / "outputs/rk3568-rng-network-20261004/boot-ram.json").read_text())
    boot[-1] = step(f"booti 400000 4000000:{initrd_hex} 3000000", "Source Linux userspace test: PID1 remains in RAM", 40)
    write("boot-ram.json", boot)
    command = "sh -c " + shlex.quote((HERE / "linux-stage.sh").read_text())
    write("linux-stage.json", [step(command, r"(?m)^MOTOR_ALIGNMENT_SCRIPTS_IN_RAM_CACHE_RELEASED\r?$", 5)])
    for name, marker, seconds in [
        ("linux-enumeration", "LINUX_ENUMERATION_COMPLETE", 15),
        ("linux-module-options", "REAL_BUSYBOX_MODULE_OPTIONS_DELIVERED", 8),
        ("linux-module-cleanup", "MODULE_AND_TEST_CONFIG_RELEASED", 5),
        ("linux-rootfs-read", "CODEC_PTY_AND_READONLY_ROOTFS_PASSED", 12),
    ]:
        write(name + ".json", [step("sh /tmp/" + name + ".sh", r"(?m)^" + marker + r"\r?$", seconds)])
    guard = (HERE / "linux-return-guard.sh").read_text()
    write("return-android.json", [
        step("sh -c " + shlex.quote(guard), r"(?m)^RAM_ONLY_RESOURCES_RELEASED\r?$", 2),
        step("dmesg", wait=2),
        step("echo b > /proc/sysrq-trigger", wait=40),
    ])
    print("PINNED_SERIAL_SESSIONS_WRITTEN")


if __name__ == "__main__":
    main()
