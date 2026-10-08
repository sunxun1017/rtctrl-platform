#!/usr/bin/env python3
"""Validate this phase's captured evidence; never contact a board."""
import gzip
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / "private"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    return (PRIVATE / name).read_text().replace("\r", "")


def require(value, message):
    if not value:
        raise ValueError(message)


def completed(text, token):
    require(re.search(r"(?m)^" + re.escape(token) + r"$", text), token)


def partition_hashes(text):
    return dict((name, digest) for digest, name in re.findall(
        r"(?m)^([0-9a-f]{64})  /dev/block/by-name/(boot|uboot|trust|dtbo|vbmeta)$",
        text))


def snapshot(name, expected_image, expected_archive):
    path = HERE / f"rootfs-{name}.img.gz"
    packed = path.read_bytes()
    image = gzip.decompress(packed)
    require(sha(packed) == expected_archive, "Snapshot archive SHA mismatch")
    require(len(image) == 67108864, "Snapshot image size mismatch")
    require(sha(image) == expected_image, "Snapshot complete image SHA mismatch")
    return {"file": path.name, "archive_bytes": len(packed),
            "archive_sha256": sha(packed), "image_bytes": len(image),
            "image_sha256": sha(image), "decompressed_image_verified": True}


def main():
    host = json.loads((HERE / "build/verification-current.json").read_text())
    tests = json.loads((HERE / "build/test-result.json").read_text())
    cleanup_tests = json.loads((HERE / "build/runtime-cleanup-result.json").read_text())
    manifest = json.loads((HERE / "rootfs-manifest.json").read_text())
    require(sha((HERE / "rootfs.img").read_bytes()) == manifest["image"]["sha256"],
            "Original host image changed")
    require(host["status"] == "HOST_ROOTFS_VERIFIED", "Host verification missing")
    require(tests["checks"] == 21 and tests["primary_image_unchanged"], "Host tests")
    require(cleanup_tests["checks"] == 7, "Cleanup tests")
    scripts = json.loads((HERE / "runtime-scripts.json").read_text())
    for name, key in (("rootfs-check.sh", "rootfs_check_sha256"),
                      ("linux-rootfs-check.sh", "linux_rootfs_check_sha256")):
        require(sha((HERE / name).read_bytes()) == scripts[key], "Runtime source SHA")
        require(cleanup_tests["sources"][name] == scripts[key], "Tested runtime SHA")
        require(scripts[key] + "  /cache/rtctrl-network-rootfs-20261004/" + name
                in read("android-staged-inputs.txt"), "Staged script differs")

    baseline = read("android-network-baseline.txt")
    android = read("android-rootfs-check.txt")
    linux = read("linux-rootfs-check.raw.txt")
    runtime = read("linux-runtime-check.raw.txt")
    returned = read("android-final-readback.txt")
    completed(baseline, "ANDROID_NETWORK_BASELINE_COMPLETE")
    completed(android, "ANDROID_NETWORK_ROOTFS_READY")
    completed(linux, "LINUX_NETWORK_ROOTFS_CHECK_COMPLETE")
    completed(returned, "ANDROID_RETURN_ROOTFS_READBACK_COMPLETE")
    completed(returned, "LINUX_MARKER_READ_BACK")
    for text in (android, linux, returned):
        completed(text, "ROOTFS_SOURCE_TEST_PASSED")
        completed(text, "ROOTFS_READONLY_AND_RAM_TMP_PASSED")
    before = partition_hashes(baseline)
    after = partition_hashes(returned)
    require(len(before) == 5 and before == after, "Startup partition SHA changed")
    require("/proc/1/exe -> /bin/busybox" in runtime, "PID1 readback missing")
    reset = read("return-android.raw.txt").split("DDR ", 1)[0]
    completed(reset, "RAM_ONLY_STATE_CONFIRMED")
    completed(reset, "NO_LOOP_REMAINS")
    require("sysrq: Resetting" in reset, "Reset event missing")
    reset_warning = bool(re.search(r"WARNING:|BUG:|Call trace:|Kernel panic", reset))
    require(not reset_warning, "Source Linux reset warning captured")

    snapshots = {
        "after_android": snapshot("after-android",
            "a67752f777c7c25b8f7aca570dfada72c68b1ef39c295f6bd8ccd207e11523fc",
            "a017be2478b88214c1d10d79e0d5450d33ed6b51fb3d3c52e4602b402e8ff4a7"),
        "after_linux": snapshot("after-linux",
            "32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3",
            "c8dfa07da4ea351d3c4b3190ce225988b65f26a938090abd8534b783d5d1d8b8")}
    transfer = json.loads((HERE / "android-transfer-result.json").read_text())
    require(transfer["roundtrip_passed"], "Android transfer failed")
    battery = read("android-current-battery.txt")
    level = re.search(r"(?m)^\s*level: (\d+)$", battery)
    require(level is not None, "Battery readback missing")
    files = ("android-network-baseline.txt", "android-rootfs-check.txt",
             "android-staged-inputs.txt", "linux-rootfs-check.raw.txt",
             "linux-runtime-check.raw.txt", "return-android.raw.txt",
             "android-final-readback.txt", "android-snapshot.txt", "linux-snapshot.txt",
             "android-current-battery.txt")
    evidence = {name: sha((PRIVATE / name).read_bytes()) for name in files}
    result = {
        "schema": 1, "date": "2026-10-04", "status": "SOURCE_ROOTFS_CROSS_KERNEL_PASSED",
        "host": {"filesystem_bytes": 67108864, "paths": host["path_count"],
                 "allocated_bytes": host["filesystem"]["allocated_bytes"],
                 "readonly_e2fsck_passed": True, "qemu_checked": True,
                 "boundary_tests": 21, "runtime_cleanup_tests": 7},
        "android_control": {"network_transfer": transfer,
                            "same_source_programs_passed": True,
                            "ram_tmp_and_image_unchanged_passed": True},
        "linux": {"kernel": manifest["kernel"], "pid1_remained_in_ram": True,
                  "chroot_payload_codec_pty_and_wpa_versions_passed": True,
                  "android_marker_read": True, "linux_marker_write_and_read": True,
                  "cache_first_readonly_then_independent_rw": True,
                  "all_test_mounts_loops_and_devpts_released": True,
                  "physical_wifi_started_this_phase": False,
                  "previous_linux_tcp_failure_resolved": False,
                  "crng_not_ready_during_wpa_version_check": True,
                  "authentication_attempted_this_phase": False,
                  "normal_reboot_poweroff_tested": False,
                  "sysrq_ram_guard_and_return_passed": True,
                  "source_linux_reset_warning_captured": reset_warning},
        "returned_android": {"release": "11", "kernel": "4.19.232",
                             "boot_completed": True, "root": True,
                             "linux_marker_readonly_readback": True,
                             "startup_partition_sha256": after,
                             "all_five_startup_partitions_unchanged": True,
                             "printk": [7, 4, 1, 7], "kptr_restrict": 2},
        "snapshots": snapshots, "runtime_scripts": scripts,
        "last_observed_power": {"battery_level_percent": int(level.group(1)),
                                "ac_powered": "AC powered: true" in battery,
                                "usb_powered": "USB powered: true" in battery,
                                "threshold_3_percent_user_reminded": True,
                                "board_operations_stopped_for_battery_change": True,
                                "reminder_paused_after_delivery": True,
                                "historical_snapshot_not_live_state": True},
        "private_evidence_sha256": evidence,
        "backup_scope": {"original_startup_artifacts_verified": 15,
                         "whole_emmc_backed_up": False,
                         "bare_metal_restore_tested": False},
        "boundaries": {"switch_root": False, "autostart": False,
                       "startup_partition_writes": False, "saveenv": False,
                       "mcu_or_motor_commands": False,
                       "manufacturer_android_so_in_image": False,
                       "firmware_binaries_remain": True,
                       "firmware_redistribution_permission_verified": False,
                       "git_commit_or_push": False}}
    (HERE / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    start = linux.index("[   51.")
    (HERE / "linux-rootfs-check.txt").write_text(linux[start:])
    filtered = "\n".join(line for line in runtime.splitlines()
                         if not re.search(r"cpuid|\bcid=", line))
    (HERE / "linux-runtime-check.txt").write_text(filtered + "\n")
    (HERE / "reset-excerpt.txt").write_text(reset)
    (HERE / "linux-snapshot-result.json").write_text(
        json.dumps(snapshots["after_linux"], indent=2) + "\n")
    print("SOURCE_ROOTFS_RESULT_RECORDED")


if __name__ == "__main__":
    main()
