#!/usr/bin/env python3
"""Build a bounded SPI diagnostic DTB while preserving the tested Image/ABI."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOARD = ROOT / "platforms/rk3568/boards/aiot-3568pq"
KERNEL = ROOT / "third_party/linux-rk3588"
ABI = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset"
UART_DTB = ROOT / "outputs/rk3568-motor-alignment-20261004/uart.dtb"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", choices=["v1", "v2", "v3"], default="v1")
    parser.add_argument("--negative-control", action="store_true",
                        help="Compile only and require the deliberately permissive audit to fail its fault test")
    args = parser.parse_args()
    output = HERE / "build" / ("dtb-" + args.revision)
    if output.exists() or output.is_symlink() or output.parent.is_symlink():
        raise ValueError("Refusing existing or symlink output")
    commit = subprocess.check_output(["git", "-C", str(KERNEL), "rev-parse", "HEAD"], text=True).strip()
    if commit != "9f9e9d18574d0914c0d192a90c3babfe1fd63c95" or subprocess.check_output(
            ["git", "-C", str(KERNEL), "status", "--porcelain"]):
        raise ValueError("Need locked clean kernel source")
    image = ROOT / "outputs/rk3568-rcu-reset-20261004/Image"
    if sha(image) != "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457":
        raise ValueError("Tested Image changed")
    config = (ABI / ".config").read_bytes()
    if config != (ROOT / "outputs/rk3568-rcu-reset-20261004/kernel.config").read_bytes():
        raise ValueError("Tested configuration changed")
    if sha(UART_DTB) != "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1":
        raise ValueError("Tested UART baseline changed")
    output.mkdir(parents=True)
    source = BOARD / "bsp/rk3568-aiot-3568pq-cap1188-spi.dts"
    preprocessed = subprocess.check_output([
        "gcc", "-E", "-P", "-nostdinc", "-undef", "-D__DTS__", "-x", "assembler-with-cpp",
        "-I", str(KERNEL / "arch/arm64/boot/dts/rockchip"), "-I", str(KERNEL / "include"), str(source)])
    spec = importlib.util.spec_from_file_location("cap_uart", BOARD / "verify-uart.py")
    uart = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(uart)
    baseline, _ = uart.rng.wifi.base.read_dtb(UART_DTB)
    handles = "\n".join('&{' + path.rsplit('/', 1)[0] + '} { phandle = <0x' + value.hex() + '>; };'
                        for path, value in sorted(baseline.items()) if path.endswith('/phandle'))
    pp = output / "cap1188-spi.pp.dts"
    pp.write_bytes(preprocessed + handles.encode() + b"\n")
    dtb = output / "cap1188-spi.dtb"
    command = [str(ABI / "scripts/dtc/dtc"), "-@", "-I", "dts", "-O", "dtb", "-o", str(dtb), str(pp)]
    compiled = subprocess.run(command, capture_output=True, check=True)
    (output / "dtc.log").write_bytes(compiled.stderr)
    test = ["python3", str(BOARD / "test-cap1188-spi-audit.py"), str(dtb), str(pp)]
    if args.negative_control:
        test += ["--audit-script", str(HERE / "private/audit-permissive-red.py")]
        failed = subprocess.run(test, capture_output=True, text=True)
        (output / "negative-control.txt").write_text(failed.stdout + failed.stderr)
        if failed.returncode == 0 or "Invalid compiled DTB accepted: SPI disabled" not in failed.stderr:
            raise ValueError("Fault test did not detect the permissive audit")
        print("CAP_REAL_DTB_PERMISSIVE_AUDIT_REJECTED_BY_FAULT_TEST")
        return
    old_log = ROOT / "outputs/rk3568-motor-alignment-20261004/build/uart-v1/dtc.log"
    warning_set = lambda data: {line.split("Warning ", 1)[1] for line in data.decode().splitlines() if "Warning " in line}
    additional = sorted(warning_set(compiled.stderr) - warning_set(old_log.read_bytes()))
    if additional:
        raise ValueError("New DTC warnings: " + repr(additional))
    audit = subprocess.check_output(["python3", str(BOARD / "verify-cap1188-spi.py"), str(dtb)])
    (output / "audit.json").write_bytes(audit)
    faults = subprocess.check_output(test)
    (output / "fault-tests.json").write_bytes(faults)
    record = {"kernel_commit": commit, "image_sha256": sha(image),
              "config_sha256": hashlib.sha256(config).hexdigest(), "dtb_sha256": sha(dtb),
              "dtb_bytes": dtb.stat().st_size, "uart_baseline_sha256": sha(UART_DTB),
              "source_sha256": sha(source), "builder_sha256": sha(Path(__file__)),
              "audit_script_sha256": sha(BOARD / "verify-cap1188-spi.py"),
              "fault_test_script_sha256": sha(BOARD / "test-cap1188-spi-audit.py"),
              "checks_passed": json.loads(audit)["checks_passed"],
              "property_changes": json.loads(audit)["property_changes"],
              "faults_rejected": json.loads(faults)["faults_rejected"],
              "new_dtc_warnings": additional, "board_tested": False,
              "reset_gpio_requested": False, "input_driver_registered": False}
    (output / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
