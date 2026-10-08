#!/usr/bin/env python3
"""Compile only the new accelerometer DTB; preserve the tested kernel Image."""
import argparse
import hashlib
import json
import importlib.util
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOARD = ROOT / "platforms/rk3568/boards/aiot-3568pq"
KERNEL = ROOT / "third_party/linux-rk3588"
BUILD = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="v1")
    args = parser.parse_args()
    if args.revision not in ["v1", "v2", "v3"]:
        parser.error("Need bounded revision name")
    output = HERE / "build" / ("dtb-" + args.revision)
    if output.exists() or output.is_symlink() or output.parent.is_symlink():
        raise ValueError("Refusing existing/symlink output")
    commit = subprocess.check_output(["git", "-C", str(KERNEL), "rev-parse", "HEAD"], text=True).strip()
    if commit != "9f9e9d18574d0914c0d192a90c3babfe1fd63c95" or subprocess.check_output(
            ["git", "-C", str(KERNEL), "status", "--porcelain"]):
        raise ValueError("Need locked clean kernel")
    config = (BUILD / ".config").read_bytes()
    if config != (ROOT / "outputs/rk3568-rcu-reset-20261004/kernel.config").read_bytes():
        raise ValueError("Tested kernel configuration changed")
    image = ROOT / "outputs/rk3568-rcu-reset-20261004/Image"
    image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
    if image_sha != "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457":
        raise ValueError("Tested kernel Image changed")
    output.mkdir(parents=True)
    source = BOARD / "bsp/rk3568-aiot-3568pq-accelerometer.dts"
    pp = subprocess.run(["gcc", "-E", "-P", "-nostdinc", "-undef", "-D__DTS__", "-x", "assembler-with-cpp",
                         "-I", str(KERNEL / "arch/arm64/boot/dts/rockchip"),
                         "-I", str(KERNEL / "include"), str(source)], capture_output=True, check=True)
    # Keep prior phandle numbers stable so the audit can compare every other byte.
    # This does not alter references or provider semantics in the portable source.
    spec = importlib.util.spec_from_file_location("accel_base_uart", BOARD / "verify-uart.py")
    uart = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(uart)
    baseline = ROOT / "outputs/rk3568-motor-alignment-20261004/uart.dtb"
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1":
        raise ValueError("Tested UART baseline changed")
    tree, _ = uart.rng.wifi.base.read_dtb(baseline)
    pins = "\n".join('&{' + path.rsplit('/', 1)[0] + '} { phandle = <0x' + value.hex() + '>; };'
                       for path, value in sorted(tree.items()) if path.endswith('/phandle'))
    (output / "accelerometer.pp.dts").write_bytes(pp.stdout + pins.encode() + b"\n")
    command = [str(BUILD / "scripts/dtc/dtc"), "-@", "-I", "dts", "-O", "dtb", "-o",
               str(output / "accelerometer.dtb"), str(output / "accelerometer.pp.dts")]
    result = subprocess.run(command, capture_output=True, check=True)
    (output / "dtc.log").write_bytes(result.stderr)
    def warnings(data):
        return {line.split("Warning ", 1)[1] for line in data.decode().splitlines() if "Warning " in line}
    old_log = ROOT / "outputs/rk3568-motor-alignment-20261004/build/uart-v1/dtc.log"
    additional_warnings = sorted(warnings(result.stderr) - warnings(old_log.read_bytes()))
    if additional_warnings:
        raise ValueError("New DTC warnings: " + repr(additional_warnings))
    audit = subprocess.run(["python3", str(BOARD / "verify-accelerometer.py"), str(output / "accelerometer.dtb")],
                           capture_output=True, check=True)
    (output / "audit.json").write_bytes(audit.stdout)
    faults = subprocess.run(["python3", str(BOARD / "test-accelerometer-audit.py"),
                             str(output / "accelerometer.dtb"), str(output / "accelerometer.pp.dts")],
                            capture_output=True, check=True)
    (output / "fault-tests.json").write_bytes(faults.stdout)
    data = (output / "accelerometer.dtb").read_bytes()
    manifest = {"kernel_commit": commit, "dtb_bytes": len(data), "dtb_sha256": hashlib.sha256(data).hexdigest(),
                "board_tested": False, "audited": True, "command": command,
                "baseline_phandles_pinned": True, "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                "kernel_image_sha256": image_sha, "kernel_config_sha256": hashlib.sha256(config).hexdigest(),
                "checks_passed": json.loads(audit.stdout)["checks_passed"],
                "faults_rejected": json.loads(faults.stdout)["faults_rejected"],
                "property_changes": json.loads(audit.stdout)["property_changes"], "new_dtc_warnings": additional_warnings,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "audit_source_sha256": hashlib.sha256((BOARD / "verify-accelerometer.py").read_bytes()).hexdigest(),
                "test_source_sha256": hashlib.sha256((BOARD / "test-accelerometer-audit.py").read_bytes()).hexdigest()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
