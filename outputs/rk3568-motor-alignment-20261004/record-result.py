#!/usr/bin/env python3
"""Verify captured milestones and publish only typed, non-identifying results."""
import hashlib
import json
from pathlib import Path
import re
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXPECTED = {
    "boot": "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28",
    "uboot": "4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e",
    "trust": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "dtbo": "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d",
    "vbmeta": "76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752",
}
ROOTFS_SHA = "32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    require(path.is_file() and not path.is_symlink(), "ordinary artifact required: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def captured(name):
    return (HERE / "private" / name).read_text().replace("\r", "")


def milestone(name, marker):
    value = captured(name)
    require(re.search(r"^" + re.escape(marker) + r"$", value, re.M), "missing actual milestone: " + marker)
    return value


def main():
    before = milestone("android-serial-baseline.txt", "ANDROID_SERIAL_PASSIVE_BASELINE_COMPLETE")
    after = milestone("android-after.txt", "ANDROID_RETURN_AND_STARTUP_FINGERPRINTS_READ_COMPLETE")
    for name, digest in EXPECTED.items():
        expression = r"^" + digest + r"\s+/dev/block/by-name/" + name + r"$"
        require(re.search(expression, before, re.M) and re.search(expression, after, re.M), "startup hash mismatch: " + name)
    require(ROOTFS_SHA + "  /cache/rtctrl-network-rootfs-20261004/rootfs.img" in after, "old rootfs changed")
    require(re.search(r"^4\.19\.232\n11\n1$", after, re.M), "Android release/boot incomplete")
    require(re.search(r"^7\s+4\s+1\s+7\n2$", after, re.M), "diagnostic settings differ")
    battery = int(re.search(r"^  level: (\d+)$", after, re.M)[1])
    enumeration = milestone("linux-enumeration.raw.txt", "LINUX_ENUMERATION_COMPLETE")
    require(enumeration.count("mmio:0xFDD50000 irq:24 tx:0 rx:0") == 2, "UART observation window differs")
    require("pin 16 (gpio0-16): fdd50000.serial" in enumeration
            and "pin 17 (gpio0-17): fdd50000.serial" in enumeration, "UART pins not bound")
    require("4:64\nN\n" in enumeration, "UART character number/console mismatch")
    require("Channels: 8" in enumeration and "Rates: 16000" in enumeration
            and "Format: S16_LE" in enumeration and "Status: Stop" in enumeration, "USB capture metadata mismatch")
    milestone("linux-rootfs-read.raw.txt", "CODEC_PTY_AND_READONLY_ROOTFS_PASSED")
    module = milestone("linux-module-options-v3.raw.txt", "REAL_BUSYBOX_MODULE_OPTIONS_DELIVERED")
    require(re.search(r"\[\s*590\.\d+\].*Final conf_path=/config-uart-stage.txt", module), "missing fresh v3 config-path log")
    require(re.search(r"\[\s*590\.\d+\].*\(12 bytes\) open success", module), "missing fresh v3 config load")
    require("/lib/firmware/fw_bcm43456c5_ag.bin\n/lib/firmware/nvram_ap6256.txt\n" in module, "readable module parameters mismatch")
    milestone("linux-module-cleanup-v3.raw.txt", "MODULE_AND_TEST_CONFIG_RELEASED")
    milestone("linux-restore-empty-fw-path.raw.txt", "FIRMWARE_CLASS_EMPTY_VALUE_RESTORED_BYTE_EXACT")
    final = captured("linux-final-state-v2.raw.txt")
    require("|/bin/sh./init.|" in final and "mmio:0xFDD50000 irq:24 tx:0 rx:0" in final, "RAM PID1/final UART differs")
    require("00000000  0a " in final and "00000001" in final, "firmware path byte proof absent")
    returned = milestone("return-android.raw.txt", "RAM_ONLY_RESOURCES_RELEASED")
    reset = re.search(r"\[\s*(\d+\.\d+)\] sysrq: Resetting\nDDR ", returned)
    require(reset, "actual SysRq/DDR handoff missing")
    source_tail = returned[:reset.end() - len("DDR ")]
    warnings = [line for line in source_tail.splitlines() if re.search(r"WARNING:|BUG:|Call trace:", line)]
    require(not warnings, "source kernel warning captured: " + repr(warnings))
    dtb_manifest = json.loads((HERE / "build/uart-v1/manifest.json").read_text())
    userspace = json.loads((HERE / "userspace-manifest.json").read_text())
    tests = json.loads((HERE / "build/runtime-v2-tests/v2/green-result.json").read_text())
    for name, digest in tests["actual_script_sha256"].items():
        require(sha(HERE / name) == digest, "tested runtime script changed: " + name)
    require(sha(HERE / "uart.dtb") == dtb_manifest["dtb_sha256"], "DTB identity changed")
    require(sha(HERE / "initramfs.cpio.gz") == userspace["artifact"]["sha256"], "initramfs identity changed")
    for address, path in [("00400000", ROOT / "outputs/rk3568-rcu-reset-20261004/Image"),
                          ("03000000", HERE / "uart.dtb"), ("04000000", HERE / "initramfs.cpio.gz")]:
        data = path.read_bytes()
        crc = f"{zlib.crc32(data):08x}"
        load = captured("load-ram.raw.txt")
        require(re.search(r"crc32 for " + address + r" .* ==> " + crc, load), "U-Boot CRC differs")
        require(str(len(data)) + " bytes read" in load, "U-Boot artifact size differs")
    evidence = {}
    for name in ["android-serial-baseline.txt", "android-peripheral-baseline.txt", "uboot-console.raw.txt",
                 "load-ram.raw.txt", "boot-ram.raw.txt", "linux-stage.raw.txt", "linux-enumeration.raw.txt",
                 "linux-rootfs-read.raw.txt", "linux-module-options-v2.raw.txt", "linux-module-cleanup-v2.raw.txt",
                 "linux-restore-empty-fw-path.raw.txt", "linux-module-options-v3.raw.txt",
                 "linux-module-cleanup-v3.raw.txt", "linux-final-state.raw.txt", "linux-final-state-v2.raw.txt",
                 "return-android.raw.txt", "android-after.txt", "android-firmware-directory.json"]:
        evidence[name] = {"sha256": sha(HERE / "private" / name), "public": False}
    result = {
        "schema": 1, "status": "UART0_USB_METADATA_AND_NEW_RAM_USERSPACE_BOARD_VERIFIED",
        "kernel_image_sha256": dtb_manifest["kernel_image_sha256"],
        "dtb_sha256": dtb_manifest["dtb_sha256"], "dtb_property_changes": dtb_manifest["property_changes"],
        "dtb_audit_checks": dtb_manifest["checks_passed"], "real_dtb_faults_rejected": dtb_manifest["real_dtb_faults_rejected"],
        "initramfs": userspace["artifact"], "busybox_sha256": "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1",
        "busybox_applet_count": userspace["busybox_applet_count"], "previous_51_applet_report_corrected": True,
        "uart": {"physical_address": "0xfdd50000", "linux_device": "/dev/ttyS0", "driver": "dw-apb-uart",
                 "major_minor": "4:64", "console": False, "pinmux_gpio_numbers": [16, 17],
                 "observation_seconds": 10, "initial_tx_rx": [0, 0], "final_tx_rx": [0, 0],
                 "physical_tty_opened": False, "termios_115200_8n1_board_verified": False,
                 "application_motor_frames_sent": False, "electrical_zero_tx_proven": False,
                 "motor_controller_physical_correspondence_verified": False, "motors_connected": False,
                 "controller_connection_confirmed": False, "fd_snapshot_exclusivity_proven": False},
        "usb_microphone": {"driver": "snd-usb-audio", "format": "S16_LE", "channels": 8,
                           "sample_rate": 16000, "capture_state": "Stop", "matches_android_metadata": True,
                           "audio_samples_recorded": False, "channel_meanings_or_audio_quality_verified": False},
        "codec_and_posix_pty_on_source_kernel_passed": True,
        "old_rootfs_sha256_unchanged": ROOTFS_SHA, "old_rootfs_busybox_replaced": False,
        "new_busybox_real_module_arguments_verified": True, "module_config_bytes": 12,
        "module_config_pm_band_parsed": [0, 1], "firmware_pm_readback_or_network_auth_tested": False,
        "v2_firmware_path_restoration_was_false": True, "v2_getter_before_after_hex": ["0a", "0a0a"],
        "firmware_path_repaired_getter_hex": "0a", "v3_firmware_search_path_not_modified": True,
        "runtime_failure_tests_passed": tests["cases_passed"],
        "new_kernel_or_module_built": False, "normal_reboot_poweroff_validated": False,
        "sysrq_reset_seconds": float(reset[1]), "source_kernel_warning_bug_calltrace_captured": warnings,
        "ram_pid1": "/bin/sh /init", "switch_root_performed": False,
        "loops_cache_debugfs_devpts_and_test_module_released": True,
        "android_11_root_boot_completed_after": True, "startup_partition_sha256_unchanged": EXPECTED,
        "battery_percent_at_return": battery, "printk_at_return": [7, 4, 1, 7], "kptr_restrict_at_return": 2,
        "serial_host_port_released": True, "credentials_packaged_or_new_wifi_authentication": False,
        "startup_partition_write_saveenv_commit_push_performed": False,
        "vendor_firmware_redistribution_license_verified": False,
        "stop_enable_feedback_contract_or_physical_motor_verified": False,
        "reference_audit_sha256": sha(HERE / "reference-audit.json"),
        "firmware_source_audit_sha256": sha(HERE / "firmware-source-audit.json"), "evidence": evidence,
        "remaining": ["motor firmware/protocol and safe stop", "MXC6655 driver error propagation and identity",
                      "CAP1188 SPI", "RK809 board audio", "display/camera/BT", "normal power lifecycle and persistent Linux entry"],
    }
    (HERE / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ["status", "dtb_audit_checks", "real_dtb_faults_rejected",
                     "runtime_failure_tests_passed", "sysrq_reset_seconds", "battery_percent_at_return"]}, indent=2))


if __name__ == "__main__":
    main()
