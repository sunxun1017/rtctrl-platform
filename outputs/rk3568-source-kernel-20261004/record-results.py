#!/usr/bin/env python3
"""Verify this run's private evidence before writing its public result."""
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PRIVATE = HERE / "private"
RELEASE = "5.10.160-rt89-g9f9e9d18574d-dirty"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(name):
    return (PRIVATE / name).read_text().replace("\r", "")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    load = read("load-ram.raw.txt")
    boot = read("boot-ram.raw.txt")
    linux = read("linux-check.raw.txt")
    final = read("linux-final-check.raw.txt")
    android = read("android-final.raw.txt")
    returned = read("return-android.raw.txt")
    network = read("android-network-final.raw.txt")
    manifest = json.loads((PRIVATE / "dtb/manifest.json").read_text())

    artifacts = []
    inputs = (
        ("Image", HERE.parent / "rk3568-boot-preparation-20260928/Image",
         34888192, "c0efb3bb522005cf106500c26c5c2c02d5905c2bfa9ecb273c2663db20aad4ec", "7740ca58", 0x400000),
        ("firstboot.dtb", PRIVATE / "dtb/rk3568-aiot-3568pq-firstboot.dtb",
         161378, "20c8f026b71fe4e8a8752a9407087eb05b4e4819b3fa7e2f4845be17727d8c15", "8df189f6", 0x3000000),
        ("initramfs.cpio.gz", HERE.parent / "rk3568-boot-preparation-20260928/initramfs.cpio.gz",
         533234, "2a97a6a3af2054417cd47459770629673a4655131a77c3a12dd8d30568854956", "b9718d95", 0x4000000),
    )
    for name, path, size, digest, crc, address in inputs:
        data = path.read_bytes()
        require(len(data) == size and sha(path) == digest, f"Artifact mismatch: {name}")
        require(f"{zlib.crc32(data):08x}" == crc, f"Local CRC mismatch: {name}")
        require(f"==> {crc}" in load and f"{size} bytes read" in load,
                f"Board load evidence missing: {name}")
        artifacts.append({"file": name, "bytes": size, "sha256": digest,
                          "crc32": crc, "load_address": hex(address)})
    image = inputs[0][1].read_bytes()
    require(struct.unpack_from("<Q", image, 8)[0] == 0, "Image text_offset changed")
    require(struct.unpack_from("<Q", image, 16)[0] == 0x21e0000, "Image memory span changed")
    require(manifest["dtb_sha256"] == artifacts[1]["sha256"], "DTB build manifest mismatch")

    require("booti 400000 4000000:822f2 3000000" in boot, "Boot command missing")
    require("Starting kernel ..." in boot and f"Linux version {RELEASE}" in boot,
            "Source kernel startup missing")
    require(f"\n{RELEASE}\n" in linux and "|/bin/sh./init.|" in linux, "Kernel/PID1 mismatch")
    require(re.search(r"(?m)^SOURCE_KERNEL_CHECK_COMPLETE$", linux), "Runtime checks incomplete")
    require(re.search(r"(?m)^RAM_ONLY_STATE_CONFIRMED$", final), "RAM mount guard missing")
    mounts = re.findall(r"(?m)^(\S+) (\S+) (\S+) \S+ \d+ \d+$", linux + final)
    require(mounts and {row[2] for row in mounts} == {"rootfs", "devtmpfs", "proc", "sysfs", "tmpfs"},
            "Unexpected or missing filesystem evidence")
    for driver in ("i2c/drivers/rk808", "i2c/drivers/fan53555-regulator", "fe710000.tsadc"):
        require(driver in linux, f"Driver binding missing: {driver}")
    require("fdc20000.syscon:io-domains ->" in final, "IO domain binding missing")
    require("1f0000000-1ffffffff : reserved" in linux, "High reserved range missing")
    require("ed f0 00 00" in linux and "00 2f 7b 00" in linux, "Runtime logo range mismatch")
    require("ef f0 00 00" in linux and "00 00 80 00" in linux, "Runtime LUT range mismatch")
    require(re.search(r"(?m)^-r--r--r--\s+1\s+0 .*buffer@1f0000000/no-map$", linux),
            "Runtime no-map property missing")
    require("04 00 00 00" in linux and "04 08 22 f2" in linux, "Runtime initrd range mismatch")
    require("37222\n37222" in linux and "36111\n36111" in final, "Temperature evidence changed")
    require("199.19 795.48" in final, "Observed uptime missing")
    fatal = re.findall(r"(?m)^.*(?:Kernel panic|Oops:|BUG:|Call trace:).*$", boot + linux + final)
    require(not fatal, "Fatal kernel diagnostic in captured window")

    require("echo b > /proc/sysrq-trigger" in returned and "U-Boot" in returned,
            "Requested RAM-only reset and loader return missing")
    for value in ("11", "1", "4.19.232"):
        require(f"\n{value}\n" in android, f"Android return missing: {value}")
    require("uid=0(root)" in android, "Android root shell missing")
    require(re.search(r"(?m)^7\s+4\s+1\s+7$", android), "printk readback missing")
    backup = json.loads((HERE.parent / "rk3568-backup-linux-20261003/manifest.json").read_text())
    partition_hashes = {}
    for artifact in backup["artifacts"]:
        if artifact["file"].startswith("original/"):
            name = Path(artifact["file"]).stem
            digest = artifact["sha256"]
            require(f"{digest}  /dev/block/by-name/{name}" in android, f"Partition mismatch: {name}")
            partition_hashes[name] = digest
    require(len(partition_hashes) == 5, "Startup partition coverage changed")
    require("running\n" in network and "5555\n" in network and "100% packet loss" in network,
            "Final network diagnostics missing")

    result = {
        "date": "2026-10-04", "board_boot_tested": True, "deployable": False,
        "kernel_release": RELEASE, "kernel_commit": manifest["kernel_commit"],
        "kernel_patch": "platforms/rk3568/boards/aiot-3568pq/patches/0001-arm64-cache-kasan-include.patch",
        "kernel_patch_sha256": sha(REPO / "platforms/rk3568/boards/aiot-3568pq/patches/0001-arm64-cache-kasan-include.patch"),
        "kernel_config_sha256": sha(HERE.parent / "rk3568-boot-preparation-20260928/kernel.config"),
        "kernel_image_rebuilt_this_run": False, "dtb_rebuilt_this_run": True,
        "dtb_sources": manifest["sources"], "artifacts": artifacts,
        "image_text_offset": 0, "image_memory_bytes": 35520512,
        "pid1": "/bin/sh /init", "userspace": "static BusyBox 1.36.1 RAM initramfs",
        "filesystem_types": sorted({row[2] for row in mounts}),
        "persistent_block_filesystems_mounted_in_linux": False,
        "emmc_enumerated": True, "linux_emmc_device": "mmcblk0",
        "bound_drivers": ["fan53555-regulator", "rk808", "rockchip-iodomain", "rockchip-thermal"],
        "runtime_memory_reg_bytes": 192,
        "runtime_high_buffer": {"address": "0x1f0000000", "bytes": 268435456, "no_map": True},
        "runtime_drm_logo": {"address": "0xedf00000", "bytes": 3111680},
        "runtime_drm_cubic_lut": {"address": "0xeff00000", "bytes": 32768},
        "runtime_initrd": {"start": "0x04000000", "end": "0x040822f2"},
        "observed_uptime_seconds": 199.19, "temperature_millidegrees_c": [37222, 36111],
        "fatal_diagnostics_in_captured_window": fatal, "warning_free": False,
        "long_term_stability_tested": False, "realtime_latency_tested": False,
        "return_method": "RAM-only mount guard, then requested SysRq immediate reset",
        "normal_shutdown_lifecycle_validated": False, "original_android_restored": True,
        "original_android_version": "11", "original_android_kernel": "4.19.232",
        "original_android_boot_completed": True, "startup_partition_sha256": partition_hashes,
        "five_startup_partition_hashes_unchanged": True,
        "boot_partition_write_performed": False, "saveenv_performed": False,
        "ordinary_files_staged_on_android": True, "kernel_probe_hardware_register_writes": True,
        "motor_commands_sent": False, "physical_mcu_ack_tested": False,
        "original_ddr_loader_trust_binaries_retained": True,
        "final_adb_connected": False, "final_adbd_running": True,
        "final_android_wlan_ipv4_present": True, "final_router_ping": "2 sent, 0 received",
        "serial_port_released": True, "printk_readback": [7, 4, 1, 7],
        "raw_evidence_sha256": {
            name: sha(PRIVATE / name) for name in (
                "preflight.raw.txt", "uboot-console.raw.txt", "load-ram.raw.txt", "boot-ram.raw.txt",
                "linux-check.raw.txt", "linux-final-check.raw.txt", "return-android.raw.txt",
                "android-final.raw.txt", "android-network-final.raw.txt")
        },
    }
    (HERE / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    runtime = linux + "\n# Final readbacks\n" + final
    runtime = re.sub(r"\b(cpuid|cid|androidboot\.serialno)=[^\s]+", r"\1=<redacted>", runtime)
    (HERE / "linux-runtime-check.txt").write_text(runtime)
    selected = [line for line in boot.splitlines() if any(marker in line for marker in (
        "== DO RELOCATE ==", "Linux version", "Machine model", "Kernel command line:",
        "SCMI protocol", "IRQ fiq", "IRQ wakeup", "nmi irq handler", "Failed to locate of_node",
        "Failed to find matching dt id", "rga iommu bind failed", "rga_iommu_bind",
        "regulatory.db", "Run /init as init process", "return:", "external"))]
    excerpt = "\n".join(selected) + "\n"
    excerpt = re.sub(r"\b(cpuid|cid|androidboot\.serialno)=[^\s]+", r"\1=<redacted>", excerpt)
    excerpt = re.sub(r"\([^()]*@[^()]*\)", "(<builder>)", excerpt)
    (HERE / "boot-excerpt.txt").write_text(excerpt)
    print(f"PASS: {RELEASE}; RAM mounts; runtime reservations; Android return; 5 partition hashes")
    print("Final state: serial released; Android booted; network ADB not reachable")


if __name__ == "__main__":
    main()
