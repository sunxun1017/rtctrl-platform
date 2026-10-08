#!/usr/bin/env python3
"""Validate local raw evidence and publish only bounded, non-sensitive results."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIVATE = HERE / "private"
EXPECTED = {
    "/dev/block/by-name/boot": "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28",
    "/dev/block/by-name/uboot": "4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e",
    "/dev/block/by-name/trust": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "/dev/block/by-name/dtbo": "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d",
    "/dev/block/by-name/vbmeta": "76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752",
    "/cache/rtctrl-source-userspace-20261004/rootfs.ext4": "4fcebae566d889072954b2f5b220474fe9accd75bbb48471023f24841b6ed95e",
    "/cache/rtctrl-network-rootfs-20261004/rootfs.img": "32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw(name):
    return (PRIVATE / name).read_text().replace("\r", "")


def require(text, pattern):
    if not re.search(pattern, text, re.M):
        raise ValueError("Required evidence missing: " + pattern)


def fingerprints(text):
    return {path: digest for digest, path in re.findall(r"^([0-9a-f]{64})  (/[^\n]+)$", text, re.M)}


def main():
    names = ["android-baseline.raw.txt", "android-stage.raw.txt", "load-ram.raw.txt", "boot-ram.raw.txt",
             "linux-stage.raw.txt", "linux-enumeration.raw.txt", "linux-runtime-v2-upload.raw.txt",
             "linux-identity.raw.txt", "linux-after-identity.raw.txt", "release-after-debugfs.raw.txt",
             "return-android.raw.txt", "android-after.raw.txt", "android-final-state.raw.txt"]
    logs = {name: raw(name) for name in names}
    before, after = logs["android-baseline.raw.txt"], logs["android-after.raw.txt"]
    for text in [before, after]:
        require(text, r"^ANDROID_CAP_BASELINE_COMPLETE$")
        require(text, r"^4\.19\.232\n11\n1$")
        require(text, r"^/sys/bus/spi/drivers/cap1188$")
        require(text, r'^N: Name="cap1188_input"$')
        require(text, r"^B: KEY=3fc$")
        if fingerprints(text) != EXPECTED:
            raise ValueError("Startup or previous rootfs fingerprint differs")
    require(logs["android-stage.raw.txt"], r"^CAP_INPUTS_STAGED$")
    for crc in ["c91762d1", "2bc429db", "74fea1e6"]:
        require(logs["load-ram.raw.txt"], "==> " + crc)
    require(logs["boot-ram.raw.txt"], r"^Source Linux userspace test: PID1 remains in RAM$")
    require(logs["linux-stage.raw.txt"], r"^CAP_INPUTS_IN_RAM_CACHE_RELEASED$")
    require(logs["linux-runtime-v2-upload.raw.txt"], r"^CAP_RUNTIME_V2_HASHES_VERIFIED$")
    enum = logs["linux-enumeration.raw.txt"]
    require(enum, r"^CAP_SPI_ENUMERATION_COMPLETE_NO_DEVICE_OPEN$")
    require(enum, r"^153:0$")
    require(enum, r"^crw-------\s+1\s+153,\s+0 .* /dev/spidev3\.0$")
    require(enum, r"^00000001\n000186a0$")
    require(enum, r'^N: Name="rk805 pwrkey"$')
    if "cap1188_input" in enum:
        raise ValueError("Unexpected CAP input registration")
    identity = logs["linux-identity.raw.txt"]
    require(identity, r"^CAP1188 identity mismatch: product=0x00 manufacturer=0x00$")
    require(identity, r"^CAP_SPI_IDENTITY_REJECTED_RC=1$")
    require(identity, r"^CAP_SPI_DIAGNOSTIC_COMPLETE_NO_INPUT_DRIVER$")
    counts = {}
    for field, expected in {"MESSAGES_BEFORE": 0, "MESSAGES_AFTER": 3, "ERRORS_BEFORE": 0, "ERRORS_AFTER": 0,
                            "TIMEOUTS_BEFORE": 0, "TIMEOUTS_AFTER": 0}.items():
        require(identity, r"^CAP_SPI_" + field + "=" + str(expected) + r"$")
        counts[field] = expected
    if "CAP1188_IDENTITY_VERIFIED" in identity or "CAP_SPI_IDENTITY_ACCEPTED" in identity:
        raise ValueError("Unexpected identity success")
    for text in [enum, identity]:
        if len(re.findall(r"^0: uart:16550A mmio:0xFDD50000 irq:\d+ tx:0 rx:0$", text, re.M)) < 1:
            raise ValueError("UART0 counter evidence missing")
    post = logs["linux-after-identity.raw.txt"]
    for pin in [146,147,149]:
        require(post, rf"^pin {pin} .*function spi3-hs group spi3m1-pins$")
    require(post, r"^pin 14 .*\(MUX UNCLAIMED\) \(GPIO UNCLAIMED\)$")
    require(post, r"^pin 150 .*function spi3 group spi3m1-cs0$")
    require(post, r"^pin 153 .*\(MUX UNCLAIMED\) \(GPIO UNCLAIMED\)$")
    require(logs["release-after-debugfs.raw.txt"], r"^CAP_AFTER_IDENTITY_DEBUGFS_RELEASED$")
    returned = logs["return-android.raw.txt"]
    require(returned, r"^CAP_RAM_ONLY_RESET_READY$")
    reset = re.search(r"^\[\s*([0-9.]+)\] sysrq: Resetting\nDDR ", returned, re.M)
    if not reset:
        raise ValueError("Source reset to DDR boundary missing")
    source_segment = returned[:reset.end() - 4]
    if re.search(r"WARNING:|BUG:|Call trace:", source_segment):
        raise ValueError("Source warning/oops remains")
    final = logs["android-final-state.raw.txt"]
    require(final, r"^uid=0\(root\)")
    require(final, r"^4\.19\.232\n11\n1$")
    battery_before = int(re.search(r"^  level: (\d+)$", before, re.M).group(1))
    battery_after = int(re.search(r"^  level: (\d+)$", final, re.M).group(1))
    runtime = json.loads((HERE / "runtime-manifest-v2.json").read_text())
    for name, expected in runtime["files"].items():
        path = HERE / name if name.endswith(".sh") else HERE / "build/staging-v1" / name
        if sha(path) != expected:
            raise ValueError("Current tested input changed: " + name)
    if sha(HERE / "linux-stage.sh") != runtime["stage_script_sha256"]:
        raise ValueError("Stage script changed")
    host = json.loads((HERE / "build/host-checks-v3/result.json").read_text())
    if host["status"] != "CAP_CURRENT_HOST_ARTIFACTS_VERIFIED":
        raise ValueError("Host verification missing")
    actual = host["actual_runtime_checks"]
    for name, expected in actual["check-runtime-commands.py"]["script_sha256"].items():
        if sha(HERE / name) != expected:
            raise ValueError("Host script evidence stale: " + name)
    if actual["test-return-guard.py"]["guard_sha256"] != sha(HERE / "linux-return-guard.sh"):
        raise ValueError("Host guard evidence stale")
    if host["stage_fixture_result"]["source_sha256"] != sha(HERE / "linux-stage.sh"):
        raise ValueError("Host stage evidence stale")
    result = {
        "status": "CAP_SPI_RAM_DIAGNOSTIC_RETURNED_IDENTITY_REJECTED",
        "date": "2026-10-04",
        "linux_kernel": "5.10.160-rt89-g9f9e9d18574d-dirty",
        "dtb": {"bytes": 162562, "sha256": runtime["files"]["cap1188-spi.dtb"], "crc32": "2bc429db",
                "checks": 151, "faults_rejected": 15, "property_changes": 10, "old_phandles_retained": 760,
                "new_dtc_warnings": 0, "i2c5_enabled": False, "spi_m1_default_and_hs": True, "only_cs0": True},
        "helper": {"sha256": runtime["files"]["cap1188-inspect"], "host_checks": 42, "qemu_checks": 42,
                   "static_open_source": True, "configuration_writes": 0, "maximum_identity_transactions": 3},
        "android_baseline": {"input_name": "cap1188_input", "key_capability": "3fc", "keycodes": list(range(2,10)),
                             "binding": "cap1188", "fresh_physical_identity_verified": False},
        "linux_identity": {"device": "spidev3.0", "device_numbers": "153:0", "spi_mode": 3,
                           "bits_per_word": 8, "speed_hz": 100000, "lsb_first": False,
                           "product": "0x00", "manufacturer": "0x00", "revision": "not reported on mismatch",
                           "registers_read": ["0xfd", "0xfe", "0xff"], "exit_code": 1, "accepted": False,
                           "counters": counts, "pinmux_after": "spi3-hs on M1; CS0 M1; CS1/reset unclaimed",
                           "controller_error_free_is_not_chip_ack": True, "hardware_cause_established": False},
        "boundaries": {"input_registered": False, "input_opened": False, "reset_requested": False,
                       "initialization_written": False, "modules_loaded": False, "mcu_node_present": False,
                       "uart0_tx_rx": [0,0], "motor_connected": False, "motor_action": False,
                       "saveenv": False, "startup_partition_write": False, "switch_root": False,
                       "normal_poweroff_verified": False, "all_peripherals_aligned": False},
        "runtime_checks": {"busybox_applets": 52, "reset_guard_fixtures": 25, "stage_fixtures": 18,
                           "persistent_mounts_at_reset": False, "loop_devices_at_reset": False,
                           "identity_helper_fds_at_reset": False, "source_warning_bug_call_trace_to_ddr": False,
                           "reset_seconds": float(reset.group(1))},
        "returned_android": {"kernel": "4.19.232", "release": 11, "root": True, "boot_completed": True,
                             "adb_reconnected": True, "battery_baseline_percent": battery_before,
                             "battery_final_percent": battery_after, "serial_port_released": True},
        "startup_and_previous_rootfs": {"before_after_full_sha_equal": True, "full_emmc_compared": False,
                                        "backup_restore_tested": False, "sha256": EXPECTED},
        "raw_evidence_sha256": {name: sha(PRIVATE / name) for name in names},
        "current_runtime_files": runtime["files"],
        "limitations": ["Identity rejected; no touch event/init/reset/lifecycle acceptance",
                        "No original Android direct SPI ID read: vendor driver kept bound",
                        "Electrical power/reset/CS/MISO and chip population were not measured",
                        "Other peripherals, MCU hardware feedback and motor safety contract still incomplete"]
    }
    (HERE / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "battery_final_percent": battery_after,
                      "startup_and_previous_rootfs_equal": True, "identity_verified": False}, indent=2))


if __name__ == "__main__":
    main()
