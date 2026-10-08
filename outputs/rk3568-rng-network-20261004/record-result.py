#!/usr/bin/env python3
"""Validate local evidence and emit a report without network identifiers or keys."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / "private"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return (PRIVATE / name).read_text().replace("\r", "")


def marker(name, text):
    assert re.search(r"(?m)^" + re.escape(text) + r"$", read(name)), (name, text)


def partition_hashes(name):
    return dict((partition, digest) for digest, partition in re.findall(
        r"(?m)^([0-9a-f]{64})\s+/dev/block/by-name/(boot|uboot|trust|dtbo|vbmeta)$",
        read(name)))


original = {
    "boot": "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28",
    "uboot": "4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e",
    "trust": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "dtbo": "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d",
    "vbmeta": "76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752",
}
assert partition_hashes("android-baseline.txt") == original
assert partition_hashes("android-after.txt") == original
marker("android-after.txt", "ANDROID_NETWORK_BASELINE_COMPLETE")
after = read("android-after.txt")
assert read("android-version-after.txt").strip() == "11"
assert "4.19.232\n1\nrunning\n5555\n" in after
assert "7\t4\t1\t7\n2\n" in after
battery = int(re.search(r"(?m)^\s*level: (\d+)$", after)[1])
rootfs_hash = "32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3"
assert read("android-rootfs-after.txt").startswith(rootfs_hash + "  ")

entropy = json.loads((HERE / "entropy-manifest.json").read_text())
assert sha(HERE / "entropy-check") == entropy["artifact"]["sha256"]
for line in (HERE / "upload.sha256").read_text().splitlines():
    digest, name = line.split("  ", 1)
    assert sha(HERE / name) == digest, name
marker("linux-rng.raw.txt", "RNG_CHECK_INPUTS_IN_RAM_CACHE_RELEASED")
marker("linux-rng.raw.txt", "CRNG_READY")
marker("linux-rng.raw.txt", "RNG_DRIVER_AND_CRNG_CHECK_COMPLETE")
final_linux = read("linux-final-readback.raw.txt")
crng_seconds = float(re.search(r"\[\s*(\d+\.\d+)\] random: crng init done", final_linux)[1])
assert "rootfs / rootfs " in final_linux
assert "/bin/sh\x00/init\x00" in final_linux
reset_capture = read("return-android.raw.txt")
assert re.search(r"(?m)^DDR ", reset_capture)
# Stop at the next boot ROM/DDR output, before stock Android kernel messages.
linux_reset_tail = re.split(r"(?m)^DDR ", reset_capture, maxsplit=1)[0]
crash_lines = re.findall(
    r"(?m)^(?:<\d+>)?\[\s*\d+\.\d+\].*(?:WARNING:|BUG:|Call trace:).*$",
    final_linux + "\n" + linux_reset_tail)
assert not crash_lines, crash_lines

for group, cleanup in [("default", "linux-cleanup-default.raw.txt"),
                       ("pm0-v2", "linux-cleanup-pm0-v2.raw.txt"),
                       ("band5-v3", "linux-cleanup-band5-v3.raw.txt")]:
    marker("linux-auth-" + group + ".raw.txt", "WPA_STARTED_AFTER_CRNG_READY")
    marker("linux-auth-" + group + ".raw.txt", "wpa_state=COMPLETED")
    marker("linux-dhcp-" + group + ".raw.txt", "DHCP_IPV4_CONFIGURED")
    marker(cleanup, "WIFI_CREDENTIAL_PROCESSES_MODULE_AND_INTERFACE_RELEASED")
assert "/config.txt (5 bytes) open success" in read("linux-device-pm0-v2.raw.txt")
assert "dhd_conf_read_pm_params : PM = 0" in read("linux-device-pm0-v2.raw.txt")
assert "/config.txt (12 bytes) open success" in read("linux-device-band5-v3.raw.txt")
assert "dhd_conf_read_others : band = 1" in read("linux-device-band5-v3.raw.txt")
assert "WLC_SET_BAND setting failed" not in read("linux-device-band5-v3.raw.txt")
assert "PM = 0" not in read("linux-device-pm0.raw.txt")
for mode in ("default-failure", "pm0"):
    failure = json.loads((PRIVATE / ("transfer-" + mode + ".json")).read_text())
    assert failure["roundtrip_passed"] is False
    assert failure["error"] == "Linux transfer connect timed out"

transfer = json.loads((PRIVATE / "transfer-band5.json").read_text())
payload_sha = "7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2"
assert transfer["roundtrip_passed"] is True and transfer["bytes"] == 65536
assert transfer["upload_sha256"] == transfer["download_sha256"] == payload_sha
marker("linux-transfer-verify-band5.raw.txt", "TRANSFER_ROUNDTRIP_COMPLETE")
marker("linux-transfer-verify-band5.raw.txt", "freq=5220")
assert payload_sha + "  /tmp/" in read("linux-transfer-verify-band5.raw.txt")
for text in ("TEST_PM_CONFIGURATION_RELEASED", "NETWORK_RESOURCES_RELEASED",
             "RAM_ONLY_STATE_CONFIRMED", "NO_LOOP_REMAINS"):
    marker("return-android.raw.txt", text)
reset_seconds = float(re.search(r"\[\s*(\d+\.\d+)\] sysrq: Resetting",
                               read("return-android.raw.txt"))[1])

busybox = json.loads((HERE / "busybox-module-options-manifest.json").read_text())
repo = HERE.parents[1]
assert sha(repo / busybox["artifact"]["path"]) == busybox["artifact"]["sha256"]
assert busybox["config_changes"] == {"CONFIG_FEATURE_CMDLINE_MODULE_OPTIONS": {"before": "n", "after": "y"}}
assert busybox["module_argument_mock_cases_passed"] == 4
assert busybox["board_tested"] is False
for folder, script in [("cleanup-tests", "linux-network-cleanup.sh"),
                       ("cleanup-v2-tests", "linux-network-cleanup-v2.sh")]:
    checks = json.loads((HERE / "build" / folder / "green-result.json").read_text())
    assert checks["green_cases"] == 11
    assert checks["source_sha256"] == sha(HERE / script)

result = {
    "schema": 1,
    "status": "RNG_READY_AND_CONDITIONAL_5GHZ_TCP_ROUNDTRIP_PASSED",
    "linux_release": "5.10.160-rt89-g9f9e9d18574d-dirty",
    "rng": {"driver": "rockchip-rng", "device": "fe388000.rng",
            "hwrng_current": "rockchip", "crng_init_seconds": crng_seconds,
            "getrandom_nonblock_ready": True, "statistical_quality_tested": False,
            "before_authentication": True},
    "network": {
        "default": {"completed": True, "observed_frequency_mhz": 2437,
                    "dhcp": True, "gateway_icmp": True, "peer_arp_flags": "0x0", "tcp": False},
        "pm0_parameter_attempt": {"configuration_applied": False, "authentication_attempted": False},
        "pm0_default_config": {"configuration_parsed": True, "firmware_pm_readback": False,
                               "observed_frequency_mhz": 2437, "completed": True,
                               "dhcp": True, "gateway_icmp": True, "tcp": False},
        "pm0_plus_5ghz": {"configuration_bytes": 12, "config": "PM=0\nband=a\n",
                         "band_parsed": 1, "observed_frequency_mhz": 5220,
                         "completed": True, "dhcp": True, "gateway_icmp": True,
                         "windows_icmp_reply": False, "peer_arp_flags": "0x2",
                         "tcp_roundtrip_bytes": 65536, "roundtrip_passed": True,
                         "upload_board_download_sha256": payload_sha},
        "arp_root_cause_confirmed": False, "long_term_reconnect_suspend_tested": False,
        "android_manufacturer_shared_libraries_used": False,
        "wifi_firmware_binary_dependency_retained": True,
    },
    "busybox_fix": {"configuration": "FEATURE_CMDLINE_MODULE_OPTIONS",
                    "old_options_ignored_confirmed": True, "new_config_enabled": True,
                    "new_static_binary_sha256": busybox["artifact"]["sha256"],
                    "real_objects_mocked_module_syscall_cases": 4, "board_tested": False},
    "cleanup": {"all_test_groups_released": True, "cache_ro_mount_released": True,
                "linux_final_filesystems": ["rootfs", "devtmpfs", "proc", "sysfs", "tmpfs"],
                "sysrq_reset_seconds": reset_seconds, "linux_crash_lines_captured": 0,
                "android_11_root_boot_completed": True, "startup_full_hashes": original,
                "startup_hashes_unchanged": True, "existing_rootfs_sha256": rootfs_hash,
                "existing_rootfs_unchanged": True, "final_battery_percent": battery,
                "final_printk": [7, 4, 1, 7], "final_kptr_restrict": 2,
                "boot_partition_flash_saveenv_motor_commands": False,
                "full_emmc_restore_normal_reboot_poweroff_validated": False},
    "public_source_sha256": {p.name: sha(p) for p in sorted(HERE.iterdir())
                             if p.suffix in (".sh", ".py", ".ps1", ".c")},
    "private_evidence_sha256": {p.name: sha(p) for p in sorted(PRIVATE.iterdir())
                               if p.suffix in (".txt", ".json")},
}
(HERE / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
print(result["status"])
