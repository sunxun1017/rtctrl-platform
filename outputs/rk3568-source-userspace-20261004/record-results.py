#!/usr/bin/env python3
"""Validate captured evidence, then publish this run's bounded result."""
import hashlib
import json
from pathlib import Path
import re

here = Path(__file__).resolve().parent
private = here / "private"


def read(name):
    return (private / name).read_text().replace("\r", "")


def require(condition, message):
    if not condition:
        raise ValueError(message)


kernel = json.loads((here / "kernel-artifacts.json").read_text())
userspace = json.loads((here / "userspace-artifacts.json").read_text())
boot = read("boot-ram.raw.txt")
load = read("load-ram.raw.txt")
linux = read("linux-check.raw.txt")
returned = read("return-android.raw.txt")
android = read("android-final.raw.txt")
readback = read("android-readback.txt")
prepared = read("android-rootfs-preparation.txt")
before = read("startup-before.txt")
after = read("startup-after.txt")
release = kernel["kernel_release"]
require(f"Linux version {release}" in boot and f"\n{release}\n" in linux, "Source kernel not confirmed")
require("|/bin/sh./init.|" in linux, "RAM PID1 not confirmed")
for item in kernel["artifacts"]:
    require(hashlib.sha256((here / item["file"]).read_bytes()).hexdigest() == item["sha256"], item["file"])
    require(f"==> {item['crc32']}" in load, "Load CRC missing: " + item["file"])
require(hashlib.sha256((here / "kernel.config").read_bytes()).hexdigest() == kernel["kernel_config_sha256"],
        "Kernel configuration hash changed")
board = here.parents[1] / "platforms/rk3568/boards/aiot-3568pq"
for name, digest in kernel["patches"].items():
    require(hashlib.sha256((board / "patches" / name).read_bytes()).hexdigest() == digest, "Patch changed: " + name)
for item in userspace["artifacts"]:
    require(hashlib.sha256((here / item["file"]).read_bytes()).hexdigest() == item["sha256"], item["file"])
for text in (prepared, linux):
    for marker in ("ROOTFS_SOURCE_TEST_PASSED", "PatchX codec:", "PatchX POSIX PTY:"):
        require(marker in text, "Source test proof missing: " + marker)
require("rootfs.ext4: OK" in linux and "SOURCE_ROOTFS_READONLY_PASSED" in linux, "Readonly rootfs check missing")
require("SOURCE_USERSPACE_TEST_COMPLETE" in linux and "SOURCE_KERNEL_USERSPACE_CHECK_DONE" in linux,
        "Userspace run incomplete")
require(linux.count("USERSPACE_MOUNTS_RELEASED\n") == 2, "RO/RW cleanup proof missing")
require(re.search(r"(?m)^RAM_ONLY_STATE_CONFIRMED$", returned), "RAM mount guard failed")
require(re.search(r"(?m)^NO_LOOP_REMAINS$", returned), "Loop guard failed")
require("sysrq: Resetting" in returned and "U-Boot 2017.09" in returned, "Reset/loader return missing")
require("\n4.19.232\n" in android and "uid=0(root)" in android and "\n1\n" in android,
        "Android root/boot state missing")
require("\n11\n" in android, "Android version missing")
require(re.search(r"(?m)^7\s+4\s+1\s+7$", android), "printk state missing")
require(before.strip() == after.strip(), "Startup partition hashes changed")
hashes = re.findall(r"(?m)^([0-9a-f]{64})\s+/dev/block/by-name/(\w+)$", after)
require(len(hashes) == 5, "Partition coverage mismatch")
marker_hashes = {}
for name, payload in (("android-marker", "android-source-userspace-20261004\n"),
                      ("linux-marker", "source-linux-userspace-20261004\n")):
    digest = hashlib.sha256(payload.encode()).hexdigest()
    require(digest in linux and digest in readback, "Marker did not survive return: " + name)
    marker_hashes[name] = digest
require("ANDROID_SOURCE_READBACK_CLEANUP_OK" in readback, "Android readback cleanup missing")
for driver in ("i2c/drivers/rk808", "i2c/drivers/fan53555-regulator", "fdc20000.syscon:io-domains ->", "fe710000.tsadc ->"):
    require(driver in linux, "Driver binding missing: " + driver)
require("external (fb-inner-reg-idxs unavailable: -22)" in boot, "New PMIC diagnostic missing")
for old_warning in ("SCMI protocol 17 not active", "SCMI protocol 22 not active", "rga iommu bind failed"):
    require(old_warning not in boot, "Unused driver still probed: " + old_warning)
require("rcu_note_context_switch" in returned and "pr_flush" in returned and "Call trace:" in returned,
        "Expected recorded reset warning missing")
require(not re.search(r"Kernel panic|Oops:|BUG:|Call trace:", boot), "Fatal/trace in startup capture")
runtime = re.sub(r"\b(cpuid|cid|androidboot\.serialno)=[^\s]+", r"\1=<redacted>", linux)
(here / "linux-runtime-check.txt").write_text(runtime)
bootlines = [line for line in boot.splitlines() if any(marker in line for marker in
    ("Linux version", "feedback policy", "Failed to locate of_node", "IRQ fiq", "IRQ wakeup",
     "nmi irq", "regulatory.db", "Run /init", "Kernel from"))]
excerpt = re.sub(r"\([^()]*@[^()]*\)", "(<builder>)", "\n".join(bootlines))
(here / "boot-excerpt.txt").write_text(excerpt + "\n")
resetlines = [line for line in returned.splitlines() if any(marker in line for marker in
    ("sysrq: Resetting", "WARNING: CPU:", "Call trace:", "rcu_note_context_switch+",
     "__schedule+", "schedule+", "schedule_timeout+", "msleep+", "pr_flush+", "kmsg_dump+",
     "emergency_restart+", "sysrq_handle_reboot+", "__handle_sysrq+", "write_sysrq_trigger+"))]
(here / "reset-warning.txt").write_text("\n".join(resetlines) + "\n")
result = {
    "date": "2026-10-04", "board_kernel_boot_tested": True, "deployable": False,
    "kernel": kernel, "userspace_inputs": userspace,
    "pid1_policy": "RAM /bin/sh /init; persistent rootfs used only by short-lived chroot",
    "ordinary_ext4_file_bytes": 67108864, "physical_partition_formatted": False,
    "android_source_programs_passed": True, "source_linux_programs_passed": True,
    "same_program_bytes_on_android_and_linux": True,
    "linux_readonly_cache_loop_ext4_noload_phase_passed": True,
    "linux_readwrite_cache_and_loop_phase_passed": True,
    "marker_sha256": marker_hashes, "android_marker_roundtrip_passed": True,
    "linux_marker_persisted_and_read_back_on_android": True,
    "test_mounts_and_loops_released_before_reset": True,
    "normal_shutdown_lifecycle_validated": False,
    "sysrq_reset_rcu_warning_observed": True,
    "sysrq_warning_path": "__handle_sysrq / emergency_restart / kmsg_dump / pr_flush / msleep / RCU context-switch warning",
    "warning_free": False, "long_term_stability_tested": False, "realtime_latency_tested": False,
    "scmi_17_22_and_rga_warnings_in_startup_capture": False,
    "mfd_missing_of_node_warnings_remain": True,
    "pmic_feedback_policy_changed": False, "physical_rail_voltage_measured": False,
    "original_android_restored": True, "original_android_kernel": "4.19.232",
    "original_android_boot_completed": True, "startup_partition_sha256": dict((name, digest) for digest, name in hashes),
    "five_startup_partition_hashes_unchanged": True, "flash_performed": False,
    "saveenv_performed": False, "kernel_addr_r_set_in_ram": "0x00400000",
    "manufacturer_userspace_runtime_included": False, "original_4_19_modules_included": False,
    "physical_uart_or_mcu_control_tested": False, "motor_commands_sent": False,
    "network_adb_root_verified_before_and_after_test": True,
    "network_adb_intermittent": True, "final_network_adb_root_available": False,
    "final_adbd_running": "\nrunning\n" in android, "serial_port_released": True,
    "printk_readback": [7, 4, 1, 7], "raw_evidence_sha256": {
        name: hashlib.sha256((private / name).read_bytes()).hexdigest() for name in
        ("kernel-build.log", "android-rootfs-preparation.txt", "android-boot-staging.txt", "load-ram.raw.txt",
         "boot-ram.raw.txt", "linux-check.raw.txt", "return-android.raw.txt", "android-readback.txt",
         "startup-before.txt", "startup-after.txt", "android-final.raw.txt")
    }
}
(here / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("PASS: Android/source Linux tests; RO/RW rootfs; markers persisted; cleanup; Android return; 5 partition hashes")
print("Known limitation: SysRq RCU warning captured; normal lifecycle not validated")
