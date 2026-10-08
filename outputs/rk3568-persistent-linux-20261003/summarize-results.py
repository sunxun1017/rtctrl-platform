#!/usr/bin/env python3
"""Check saved board evidence before publishing this stage's result."""
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parent


def read(name):
    return (root / name).read_text().replace("\r", "")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


manifest = json.loads(read("artifacts.json"))
for filename, size_key, hash_key in (
    ("persistent-initramfs.cpio.gz", "initramfs_bytes", "initramfs_sha256"),
    ("rootfs.tar.gz", "rootfs_archive_bytes", "rootfs_archive_sha256"),
):
    content = (root / filename).read_bytes()
    require(len(content) == manifest[size_key], f"{filename}: length differs")
    require(hashlib.sha256(content).hexdigest() == manifest[hash_key], f"{filename}: hash differs")

load = read("ram-load.raw.txt")
for crc in ("28e3a67c", "60dbf153", manifest["initramfs_crc32"]):
    require("==> " + crc in load, f"Missing board CRC {crc}")
boot = read("ram-boot.raw.txt")
require("rtctrl persistent-rootfs test; PID1 remains in RAM" in boot, "RAM init did not run")
baseline = read("linux-baseline.raw.txt")
require("/bin/sh\0/init\0" in baseline, "PID1 differs")
require("PARTNAME=cache" in baseline and "\n786432\n" in baseline, "Cache identity differs")
require("RKNPU driver: v0.7.2" in baseline, "Missing Linux NPU version")
rootfs = read("linux-rootfs.raw.txt")
require("ROOTFS_ENTER loop=/dev/loop0" in rootfs, "Rootfs did not open")
require("\nROOTFS_BASELINE_END\n" in rootfs, "Rootfs baseline failed")
for entry in ("bcmdhd.ko: OK", "fw_bcm43456c5_ag.bin: OK", "nvram_ap6256.txt: OK"):
    require(entry in rootfs, f"Missing file verification: {entry}")
wifi = read("linux-wifi-path-bytes.raw.txt")
require("BROADCAST,MULTICAST,UP,LOWER_UP" in wifi, "Wi-Fi interface did not open")
for entry in (
    "/fw_bcm43456c5_ag.bin (611103 bytes) open success",
    "/nvram_ap6256.txt (2874 bytes) open success",
    "version 7.45.96.150",
):
    require(entry in wifi, f"Missing firmware result: {entry}")
cleanup = read("linux-cleanup.raw.txt")
require("\nWIFI_MODULE_REMOVED\n" in cleanup, "Wi-Fi module still loaded")
require("\nROOTFS_CLEANUP_OK\n" in cleanup, "Rootfs cleanup failed")
require("\nSTORAGE_CLEAN\n" in cleanup, "Ext4 mounts remain")
loop_check = read("linux-loop-check.raw.txt")
require("echo $?\n0\n" in loop_check, "Loop association check failed")
require(" ext4 " not in loop_check, "Persistent mount remained before reboot")
reboot = read("linux-reboot.raw.txt")
require("reboot: Restarting system" in reboot and "U-Boot 2017.09" in reboot, "Normal reboot missing")

marker_hashes = {
    "android-marker": hashlib.sha256(b"android-baseline-20261003\n").hexdigest(),
    "linux-marker": hashlib.sha256(b"linux-persistent-20261003\n").hexdigest(),
}
readback = read("android-readback.txt")
for name, sha in marker_hashes.items():
    require(re.search(rf"(?m)^{sha}  .*/{name}$", readback) is not None, f"Readback differs: {name}")
require("\nANDROID_READBACK_CLEANUP_OK\n" in readback, "Android readback cleanup missing")

expected = {
    "boot": "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28",
    "uboot": "4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e",
    "trust": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "dtbo": "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d",
    "vbmeta": "76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752",
}
final = read("android-final-check.txt")
require(final.startswith("11\n1\n4.19.232\n"), "Android startup properties differ")
actual = {name: sha for sha, name in re.findall(r"(?m)^([0-9a-f]{64})  /dev/block/by-name/(\w+)$", final)}
require(actual == expected, "Startup partition hashes differ")
require(final.endswith("7\t4\t1\t7\n"), "Printk was not restored")

result = {
    "date": "2026-10-03",
    "kernel": "4.19.232 original Image and runtime FDT",
    "pid1": "RAM /bin/sh /init",
    "persistent_userspace": {"bytes": 67108864, "location": "/cache/rtctrl-linux-20261003/rootfs.ext4", "mode": "child chroot; no switch_root", "roundtrip_marker_hashes": marker_hashes, "android_readback": True},
    "wifi": {"original_module_loaded": True, "firmware_open_success": True, "firmware_version": "7.45.96.150", "interface_up": True, "router_association_tested": False, "dhcp_tested": False, "normal_module_unload": True},
    "npu": {"driver": "v0.7.2", "node": "renderD129", "inference_tested": False},
    "android_libraries": {"elf_objects_inspected": 6, "inspection": "DT_NEEDED plus existing process maps; no dlopen/function test", "glibc_musl_drop_in": False},
    "storage_cleanup_verified": True,
    "reboot": "BusyBox reboot -f after sync and storage cleanup; normal kernel restart, no SysRq",
    "returned_android": {"release": "11", "boot_completed": 1, "startup_partition_sha256": actual, "printk": [7, 4, 1, 7]},
    "boot_partition_written": False,
    "uboot_saveenv": False,
    "full_distribution_or_power_lifecycle_validated": False,
    "diagnostic_note": "Cleanup helper's last regex check failed due serial echo interleaving; independent short-command loop check passed before reboot",
}
(root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
public = [
    "Kernel: 4.19.232", "PID1: /bin/sh /init in RAM", "Cache: PARTNAME=cache, 786432 sectors", "Rootfs: regular ext4 file, 67108864 bytes, child chroot",
    "Original module + firmware file SHA checks: OK", "RKNPU: renderD129, driver v0.7.2; inference not tested",
    "Wi-Fi: original bcmdhd loaded; firmware 611103 bytes and NVRAM 2874 bytes opened successfully", "Wi-Fi firmware: 7.45.96.150; wlan0 UP/LOWER_UP; association/DHCP not tested",
    "Wi-Fi module removed; rootfs/cache mounts removed; owned loop released", "Remaining mounts before reboot: rootfs/devtmpfs/proc/sysfs/tmpfs", "Normal kernel reboot returned Android 11; boot_completed=1",
    "Android readback: both marker SHA checks match", "Original boot/uboot/trust/dtbo/vbmeta SHA unchanged", "Printk: 7 4 1 7",
]
(root / "linux-runtime-check.txt").write_text("\n".join(public) + "\n")
print("BOARD_EVIDENCE_VERIFIED: rootfs roundtrip, Wi-Fi firmware, cleanup, Android return, five startup hashes")
