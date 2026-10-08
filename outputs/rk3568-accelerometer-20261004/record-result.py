#!/usr/bin/env python3
"""Check captured milestones and publish a bounded diagnostic result."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOARD = ROOT / "platforms/rk3568/boards/aiot-3568pq"
STARTUP = {
    "boot": "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28",
    "uboot": "4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e",
    "trust": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "dtbo": "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d",
    "vbmeta": "76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752",
}
ROOTFS = {
    "/cache/rtctrl-source-userspace-20261004/rootfs.ext4":
        "4fcebae566d889072954b2f5b220474fe9accd75bbb48471023f24841b6ed95e",
    "/cache/rtctrl-network-rootfs-20261004/rootfs.img":
        "32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    require(path.is_file() and not path.is_symlink(), "Ordinary file required: " + str(path))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def capture(name):
    return (HERE / "private" / name).read_text().replace("\r", "")


def marker(name, expected):
    value = capture(name)
    require(re.search(r"^" + re.escape(expected) + r"$", value, re.M), "Missing actual marker: " + expected)
    return value


def has_hash(text, path, digest):
    return re.search(r"^" + digest + r"\s+" + re.escape(path) + r"$", text, re.M)


def main():
    before = marker("android-baseline.raw.txt", "ANDROID_ACCEL_BASELINE_COMPLETE")
    after = marker("android-after.raw.txt", "ANDROID_ACCEL_BASELINE_COMPLETE")
    for name, digest in STARTUP.items():
        path = "/dev/block/by-name/" + name
        require(has_hash(before, path, digest) and has_hash(after, path, digest), "Startup fingerprint differs: " + name)
    source_path, network_path = ROOTFS.keys()
    require(has_hash(before, source_path, ROOTFS[source_path]), "Initial source rootfs fingerprint missing")
    for path, digest in ROOTFS.items():
        require(has_hash(after, path, digest), "Returned rootfs fingerprint differs")
    # This phase's initial raw omitted the network image. Bind it to the prior
    # captured baseline instead of inventing a before measurement in this phase.
    prior = ROOT / "outputs/rk3568-motor-alignment-20261004/private/android-after.txt"
    require(has_hash(prior.read_text(), network_path, ROOTFS[network_path]), "Prior network rootfs reference missing")
    require("/sys/bus/i2c/drivers/gsensor_mxc6655" in before and "N: Name=\"gsensor\"" not in before,
            "Android baseline does not support the stated binding/input distinction")
    require("ls: /dev/gsensor: No such file or directory" in after and "devid:0xf" in after,
            "Android original failed identity evidence missing")

    final = read_json(HERE / "private/android-final-state.json")
    require(final["kernel"] == "4.19.232" and final["android_release"] == "11"
            and final["boot_completed"] == "1" and final["id"].startswith("uid=0(root)"), "Android return incomplete")
    battery = int(re.search(r"^  level: (\d+)$", final["battery"], re.M)[1])
    stage = marker("linux-stage-v3.raw.txt", "ACCEL_INPUTS_IN_RAM_CACHE_RELEASED")
    uploaded = marker("linux-runtime-v4-upload.raw.txt", "ACCEL_RUNTIME_V3_HASHES_VERIFIED")
    runtime = read_json(HERE / "runtime-manifest-v4.json")
    artifact_paths = {
        "accelerometer.dtb": HERE / "build/dtb-v3/accelerometer.dtb",
        "sensor_dev.ko": HERE / "driver-modules-v1/modules/sensor_dev.ko",
        "mxc6655xa.ko": HERE / "driver-modules-v1/modules/mxc6655xa.ko",
        "sensor-inspect": HERE / "build/inspect-v1/sensor-inspect",
    }
    for name, digest in runtime["files"].items():
        require(sha(artifact_paths.get(name, HERE / name)) == digest, "Final runtime input changed: " + name)
        require(re.search(r"^" + re.escape(name) + r": OK$", uploaded, re.M), "Missing RAM fingerprint check: " + name)
        require(re.search(r"^" + re.escape(name) + r": OK$", stage, re.M), "Missing staging fingerprint check: " + name)

    enumeration = marker("linux-enumeration-v2.raw.txt", "LINUX_ACCEL_UNBOUND_NODE_AND_BUS_VERIFIED")
    for expected in ["pin 107 (gpio3-11): fe5e0000.i2c", "pin 108 (gpio3-12): fe5e0000.i2c",
                     "pin 16 (gpio0-16): fdd50000.serial", "pin 17 (gpio0-17): fdd50000.serial"]:
        require(expected in enumeration, "Bus/pinmux evidence missing")
    probe = marker("linux-probe-v2.raw.txt", "LINUX_ACCEL_PROBE_REJECTED_NO_FALSE_BINDING")
    require("sensor_probe failed -6" in probe, "Linux errno differs")
    require("LINUX_ACCEL_IDENTITY_AND_DEFAULT_OFF_VERIFIED" not in probe, "Unexpected successful probe")
    identity = capture("linux-identity.raw.txt")
    require("register=0x0f transfer=-1 errno=6" in identity and "STANDARD_IDENTITY_RC=1" in identity,
            "Linux fixed-address diagnostic differs")
    require("mmio:0xFDD50000 irq:24 tx:0 rx:0" in identity, "Final UART counters differ")
    android_identity = marker("android-legacy-identity.raw.txt", "ORIGINAL_ANDROID_BOOT_AND_RK3X_CONTROLLER_VERIFIED")
    require("I2C_RDWR: No such device or address" in android_identity and "ANDROID_LEGACY_IDENTITY_RC=2" in android_identity,
            "Android legacy diagnostic differs")
    require("ANDROID_LEGACY24_IDENTITY_OK" not in android_identity, "Unexpected Android identity success")
    require("errno=14" in capture("android-identity.raw.txt"), "Original standard-ABI failure evidence differs")

    returned = marker("return-android.raw.txt", "ACCEL_RAM_ONLY_RESET_READY_SENSOR_MODULES_RETAINED")
    reset = re.search(r"\[\s*(\d+\.\d+)\] sysrq: Resetting\nDDR ", returned)
    require(reset, "Actual reset/DDR handoff missing")
    source_log = returned[:reset.start()]
    warnings = [line for line in source_log.splitlines() if re.search(r"WARNING:|BUG:|Call trace:", line)]
    require(not warnings, "Source-kernel warning captured")
    load = capture("load-ram.raw.txt")
    inputs = {}
    for label, address, path in [
        ("Image", "00400000", ROOT / "outputs/rk3568-rcu-reset-20261004/Image"),
        ("DTB", "03000000", artifact_paths["accelerometer.dtb"]),
        ("initramfs", "04000000", ROOT / "outputs/rk3568-motor-alignment-20261004/initramfs.cpio.gz"),
    ]:
        data = path.read_bytes()
        crc = f"{zlib.crc32(data):08x}"
        require(re.search(r"crc32 for " + address + r" .* ==> " + crc, load), "U-Boot CRC mismatch: " + label)
        require(str(len(data)) + " bytes read" in load, "U-Boot length mismatch: " + label)
        inputs[label] = {"sha256": sha(path), "bytes": len(data), "crc32": crc}

    verification_dir = HERE / "private/final-verification-v1"
    verification = read_json(verification_dir / "result.json")
    require(verification["complete"] and verification["failures"] == 0, "Final source verification incomplete")
    for item in verification["results"].values():
        require(item["exit_code"] == 0 and sha(ROOT / item["script"]) == item["script_sha256"], "Verified test script changed")
    tests = {name: read_json(verification_dir / (name + ".txt")) for name in
             ["runtime-dependencies", "reset-guard", "dtb-audit", "dtb-faults", "linux-helper"]}
    require(tests["reset-guard"]["guard_sha256"] == runtime["files"]["linux-return-guard.sh"], "Reset guard changed")
    for name, digest in tests["runtime-dependencies"]["script_sha256"].items():
        require(sha(HERE / name) == digest, "Verified RAM script changed")
    functions = read_json(HERE / verification["driver_function_result"])
    require(functions["exit_code"] == 0, "Real driver tests failed")
    function_count = sum(suite["stdout"].count(" PASS\n") for suite in functions["suites"])
    for path, digest in functions["source_sha256"].items():
        require(sha(ROOT / path) == digest, "Tested driver source changed")
    android_tests = {}
    for name in ["android_host_result", "android_qemu_result"]:
        result = read_json(HERE / verification[name])
        require(result["failures"] == 0 and sha(HERE / "android-identity.c") == result["source_sha256"],
                "Android helper test/source differs")
        android_tests[name] = len(result["cases"])
    modules = read_json(HERE / "driver-modules-v1/module-manifest.json")
    module_tests = read_json(HERE / "driver-module-tests-v2/result.json")
    require(module_tests["failure_count"] == 0 and module_tests["tests_passed"] == 14, "Module audit tests failed")
    for path, digest in module_tests["original_inputs_sha256"].items():
        require(sha(ROOT / path) == digest, "Audited module input changed")
    dtb = read_json(HERE / "build/dtb-v3/manifest.json")
    require(dtb["dtb_sha256"] == inputs["DTB"]["sha256"] and len(dtb["property_changes"]) == 15,
            "DTB preparation manifest differs")
    require(sha(BOARD / "bsp/rk3568-aiot-3568pq-accelerometer.dts") == dtb["source_sha256"], "Published DTS changed")
    candidate = read_json(HERE / "driver-source-v1/driver-source-manifest.json")
    require(sha(BOARD / "patches/0005-sensor-error-propagation.patch") == candidate["patch_sha256"], "Published patch changed")
    prepare_tests = read_json(HERE / "driver-prepare-tests-green-v2/result.json")
    require(prepare_tests["failures"] == 0 and len(prepare_tests["cases"]) == 10, "Source preparation tests failed")
    require(sha(HERE / "driver-prepare.py") == prepare_tests["script_sha256"]
            and sha(HERE / "test-driver-prepare.py") == prepare_tests["test_script_sha256"], "Tested preparer changed")
    rebuilt = read_json(HERE / "driver-source-v2/driver-source-manifest.json")
    require(rebuilt["existing_identical_patch_reused"] and rebuilt["sources"] == candidate["sources"],
            "Published patch cannot reproduce identical candidate sources")
    for path, item in candidate["sources"].items():
        require(sha(ROOT / "third_party/linux-rk3588" / path) == item["original_sha256"], "Locked original source changed")
        require(sha(HERE / "driver-source-v2" / path) == item["candidate_sha256"], "Reproduced candidate changed")
    require(subprocess.check_output(["git", "-C", str(ROOT / "third_party/linux-rk3588"), "rev-parse", "HEAD"],
                                    text=True).strip() == dtb["kernel_commit"], "Original source commit changed")
    require(not subprocess.check_output(["git", "-C", str(ROOT / "third_party/linux-rk3588"), "status", "--porcelain"]),
            "Original source tree is dirty")
    require(sha(ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/.config") == dtb["kernel_config_sha256"], "Original config changed")
    require(inputs["Image"]["sha256"] == dtb["kernel_image_sha256"] == modules["tested_image_sha256"],
            "DTB and modules are bound to a different Image")
    android_build = read_json(HERE / "build/android-identity-v1/android-identity-manifest.json")
    require(sha(HERE / "build/android-identity-v1/android-identity") == android_build["binary_sha256"], "Android binary changed")
    require(sha(HERE / "android-identity.c") == android_build["source_sha256"], "Android built source changed")

    record = {
        "status": "diagnostic_completed_sensor_address_no_response_on_android_and_linux",
        "sensor_acceptance_passed": False,
        "kernel_commit": dtb["kernel_commit"],
        "ram_boot_inputs": inputs,
        "runtime_sha256_board_verified": runtime["files"],
        "preparation_manifests_are_pre_board_snapshots": True,
        "driver_patch_sha256": candidate["patch_sha256"],
        "board_modules": {name: {key: item[key] for key in ["bytes", "sha256", "elf"]}
                          for name, item in modules["modules"].items()},
        "module_selection": modules["module_selection"],
        "kernel_config_sha256": dtb["kernel_config_sha256"],
        "android_legacy_helper_sha256": android_build["binary_sha256"],
        "tests": {
            "real_driver_function_cases": function_count,
            "module_audit_and_output_boundary_cases": module_tests["tests_passed"],
            "published_patch_source_preparation_cases": len(prepare_tests["cases"]),
            "source_preparation_test_sha256": sha(HERE / "driver-prepare-tests-green-v2/result.json"),
            "dtb_checks": tests["dtb-audit"]["checks_passed"],
            "compiled_dtb_faults_rejected": tests["dtb-faults"]["faults_rejected"],
            "linux_helper_cases": len(tests["linux-helper"]["passed"]),
            "android_helper_cases": android_tests,
            "actual_reset_script_fixture_cases": len(tests["reset-guard"]["passed"]),
            "actual_ram_busybox_applets": tests["runtime-dependencies"]["applets"],
            "fresh_verification_sha256": sha(verification_dir / "result.json"),
            "hardware_calls_mocked_in_host_tests": True,
        },
        "observed": {
            "linux_probe_errno": -6, "linux_identity_errno": 6,
            "android_legacy_identity_error": "ENXIO", "android_legacy_identity_exit": 2,
            "linux_false_binding_rejected": True, "android_binding_without_gsensor_input": True,
            "identity_0x05_measured": False, "default_off_hardware_readback_verified": False,
            "sampling_tested": False, "physical_cause_identified": False,
            "uart0_final_tx_rx": [0, 0], "module_unload_tested": False,
            "sensor_modules_retained_until_sysrq": True, "sysrq_seconds": reset[1],
            "captured_source_warning_bug_calltrace_count": len(warnings),
        },
        "returned_android": {
            "kernel": final["kernel"], "release": final["android_release"], "boot_completed": 1,
            "root_verified": True, "battery_percent": battery,
            "startup_sha256_before_after": STARTUP,
            "old_rootfs_sha256_after": ROOTFS,
            "network_rootfs_before_reference": "Prior phase android-after.txt; omitted from this phase initial raw",
        },
        "limits": [
            "No measured chip identity, sample, orientation, physical OFF, or unload acceptance",
            "ENXIO is not proof of an absent chip or a specific power/wiring defect",
            "Legacy 24-byte messages apply only to the reviewed original Image and RK3x path",
            "Register-index writes occurred; diagnostic reads are not electrically side-effect-free",
            "Five startup partition hashes are not a full eMMC comparison or a tested restore",
            "Only v1 sensor modules were board tested; v2 rebuild was a host comparison",
            "No physical motor or MCU command; motors were disconnected",
            "No boot flashing/saveenv, switch_root, calibration, or normal poweroff acceptance",
        ],
        "private_evidence_sha256": {path.name: sha(path) for path in sorted((HERE / "private").glob("*.raw.txt"))},
        "private_final_android_state_sha256": sha(HERE / "private/android-final-state.json"),
        "prior_network_rootfs_reference_sha256": sha(prior),
        "recorder_sha256": sha(Path(__file__)),
    }
    (HERE / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"status": record["status"], "tests": record["tests"], "battery_percent": battery}, indent=2))


if __name__ == "__main__":
    main()
