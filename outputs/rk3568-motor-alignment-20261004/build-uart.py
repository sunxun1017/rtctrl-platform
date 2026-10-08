#!/usr/bin/env python3
"""Compile a new offline UART0-only DT extension without modifying prior inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOARD = ROOT / "platforms/rk3568/boards/aiot-3568pq"
KERNEL = ROOT / "third_party/linux-rk3588"
BUILD = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
IMAGE_SHA = "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457"
BASELINE = ROOT / "outputs/rk3568-rng-network-20261004/wifi-rng.dtb"
BASELINE_SHA = "ab0893cea485cb9972d93dfb3eaa61ec955cbf4314a3f0f39c43b418249e8035"


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Need ordinary input: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kernel_identity():
    commit = subprocess.check_output(["git", "-C", str(KERNEL), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "-C", str(KERNEL), "status", "--porcelain"], text=True)
    if commit != COMMIT or status:
        raise ValueError("Need the locked, restored-clean kernel source")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "build/uart-v1")
    args = parser.parse_args()
    output = Path(os.path.abspath(args.output))
    allowed = HERE / "build"
    if not output.is_relative_to(allowed) or output == allowed:
        parser.error("Output must be a new child of this phase's build directory")
    current = HERE
    for part in output.relative_to(HERE).parts:
        current = current / part
        if current.is_symlink():
            parser.error("Symlink output component is forbidden")
    if os.path.lexists(output):
        parser.error("Refusing any existing output directory")
    kernel_identity()
    if sha(BASELINE) != BASELINE_SHA:
        parser.error("Tested RNG baseline SHA changed")
    config = (BUILD / ".config").read_bytes()
    if config != (ROOT / "outputs/rk3568-rcu-reset-20261004/kernel.config").read_bytes():
        parser.error("Kernel configuration differs from tested Image")
    for symbol in [b"CONFIG_SERIAL_8250=y", b"CONFIG_SERIAL_8250_DW=y", b"CONFIG_HW_RANDOM_ROCKCHIP=y"]:
        if symbol not in config.splitlines():
            parser.error("Required built-in UART/RNG configuration absent")
    image = ROOT / "outputs/rk3568-rcu-reset-20261004/Image"
    if sha(image) != IMAGE_SHA or sha(BUILD / "arch/arm64/boot/Image") != IMAGE_SHA:
        parser.error("Image binding differs from tested artifact")
    dtc = BUILD / "scripts/dtc/dtc"
    if not dtc.is_file() or dtc.is_symlink():
        parser.error("Need existing same-source DTC")
    inputs = [
        BOARD / "bsp/rk3568-aiot-3568pq-uart.dts",
        BOARD / "bsp/rk3568-aiot-3568pq-wifi.dts",
        BOARD / "bsp/rk3568-aiot-3568pq-firstboot.dts",
        BOARD / "bsp/rk3568-aiot-3568pq-power.dtsi",
        BOARD / "bsp/rk3568-aiot-3568pq-wifi-rng.dts",
        BOARD / "verify-uart.py", BOARD / "test-uart-audit.py",
        BOARD / "verify-wifi-rng.py",
        BOARD / "verify-wifi.py", BOARD / "verify-firstboot.py",
        KERNEL / "arch/arm64/boot/dts/rockchip/rk3568.dtsi",
        KERNEL / "include/dt-bindings/clock/rk3568-cru.h",
        BUILD / ".config", dtc, Path(__file__),
    ]
    sources = {path.relative_to(ROOT).as_posix(): sha(path) for path in inputs}
    output.mkdir(parents=True)
    commands = []

    def run(argv, stdout, stderr):
        commands.append(shlex.join(argv) + " > " + shlex.quote(stdout) + " 2> " + shlex.quote(stderr))
        with (output / stdout).open("xb") as out, (output / stderr).open("xb") as err:
            result = subprocess.run(argv, stdout=out, stderr=err)
        (output / "commands.sh").write_text("\n".join(commands) + "\n")
        if result.returncode:
            raise RuntimeError("Command failed; see " + str(output / stderr))

    source = BOARD / "bsp/rk3568-aiot-3568pq-uart.dts"
    pp = output / "uart.pp.dts"
    dtb = output / "rk3568-aiot-3568pq-uart.dtb"
    run(["/usr/bin/gcc", "-E", "-P", "-nostdinc", "-undef", "-D__DTS__", "-x", "assembler-with-cpp",
         "-I", str(KERNEL / "arch/arm64/boot/dts/rockchip"), "-I", str(KERNEL / "include"), str(source)],
        pp.name, "preprocess.log")
    run([str(dtc), "-@", "-I", "dts", "-O", "dtb", "-o", str(dtb), str(pp)], "compile.stdout", "dtc.log")
    run([sys.executable, str(BOARD / "verify-uart.py"), str(dtb)], "audit.json", "audit.log")
    run([sys.executable, str(BOARD / "test-uart-audit.py"), str(dtb)], "fault-tests.json", "fault-tests.log")
    run([str(dtc), "-I", "dtb", "-O", "dts", str(dtb)], "uart.compiled.dts", "decompile.log")
    baseline_log = ROOT / "outputs/rk3568-network-rootfs-20261004/build/rng-v1/dtc.log"

    def warnings(path):
        return {line.split("Warning ", 1)[1] for line in path.read_text().splitlines() if "Warning " in line}

    new_warnings = sorted(warnings(output / "dtc.log") - warnings(baseline_log))
    if new_warnings:
        raise ValueError("New UART candidate DTC warnings: " + repr(new_warnings))
    kernel_identity()
    if sources != {path.relative_to(ROOT).as_posix(): sha(path) for path in inputs} or sha(BASELINE) != BASELINE_SHA:
        raise ValueError("Build inputs changed while compiling")
    audit = json.loads((output / "audit.json").read_text())
    faults = json.loads((output / "fault-tests.json").read_text())
    manifest = {
        "schema": 1, "variant": "wifi-rng-uart0", "kernel_commit": COMMIT,
        "kernel_image_sha256": IMAGE_SHA, "kernel_config_sha256": hashlib.sha256(config).hexdigest(),
        "baseline_dtb_sha256": BASELINE_SHA,
        "dtb": dtb.name, "dtb_bytes": dtb.stat().st_size, "dtb_sha256": sha(dtb),
        "sources": sources, "property_changes": audit["property_changes"],
        "reservation_changes": [], "checks_passed": audit["checks_passed"],
        "real_dtb_faults_rejected": faults["faults_rejected"], "new_dtc_warnings": new_warnings,
        "dtc_version": subprocess.check_output([str(dtc), "--version"], text=True).strip(),
        "image_built": False, "module_built": False, "board_boot_tested": False,
        "uart_driver_binding_tested": False, "physical_motor_tested": False,
        "wifi_reassociation_or_radio_fix_proven": False, "deployable": False,
    }
    with (output / "manifest.json").open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
