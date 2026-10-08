#!/usr/bin/env python3
"""Record the completed board test only after checking captured evidence."""
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text())

def require(condition, message):
    if not condition:
        raise ValueError(message)

def read(name):
    return (root / name).read_text().replace("\r", "")

linux = read("linux-runtime-check.raw.txt")
android = read("android-final-check.raw.txt")
load = read("ram-load.raw.txt")
boot = read("linux-ram-boot.raw.txt")
require("\n4.19.232\n" in linux and "|/bin/sh./init.|" in linux, "Standalone kernel and PID1 evidence missing")
require("rootfs / rootfs rw" in linux and "tmpfs /tmp tmpfs" in linux, "RAM rootfs evidence missing")
require(not re.search(r"(?m)^/dev/.* /", linux), "Persistent block mount detected")
require("Starting kernel ..." in boot and "rdinit=/init" in boot, "New kernel boot evidence missing")
require("LINUX_CHECK_END\n#" in linux, "Runtime check incomplete")
for crc in ("28e3a67c", "60dbf153", "b9718d95"):
    require(crc in load, f"Missing load CRC: {crc}")
require("\n11\n" in android and "\n1\n" in android and "\n4.19.232\n" in android, "Android boot completion evidence missing")
require(re.search(r"(?m)^7\s+4\s+1\s+7$", android), "printk restoration evidence missing")
for artifact in manifest["artifacts"]:
    if artifact["file"].startswith("original/"):
        name = Path(artifact["file"]).stem
        require(f'{artifact["sha256"]}  /dev/block/by-name/{name}' in android, f"Partition changed: {name}")

result = {
    "date": "2026-10-03",
    "kernel": "4.19.232",
    "board_kernel_boot_tested": True,
    "standalone_userspace": True,
    "pid1": "/bin/sh /init",
    "rootfs": "RAM initramfs with static BusyBox",
    "persistent_block_filesystems_mounted_in_linux": False,
    "original_android_restored": True,
    "original_android_boot_completed": True,
    "five_startup_partition_hashes_unchanged": True,
    "flash_performed": False,
    "saveenv_performed": False,
    "motor_commands_sent": False,
    "normal_linux_shutdown_lifecycle_validated": False,
    "return_method": "SysRq immediate reboot after confirming no persistent block mounts",
    "printk_restored": [7, 4, 1, 7],
    "raw_evidence_sha256": {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("ram-load.raw.txt", "linux-ram-boot.raw.txt", "linux-runtime-check.raw.txt", "android-final-check.raw.txt")
    },
}
(root / "boot-result.json").write_text(json.dumps(result, indent=2) + "\n")
sanitized = re.sub(r"\b(cpuid|cid|androidboot\.serialno)=[^\s]+", r"\1=<redacted>", linux)
(root / "linux-runtime-check.txt").write_text(sanitized)
print(json.dumps(result, indent=2))
