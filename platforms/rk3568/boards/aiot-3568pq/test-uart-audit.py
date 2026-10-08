#!/usr/bin/env python3
"""Compile invalid UART candidates and require actual DTB audit rejection."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]
spec = importlib.util.spec_from_file_location("uart_audit", BOARD / "verify-uart.py")
uart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uart)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    args = parser.parse_args()
    candidate = args.dtb.resolve(strict=True)
    uart.audit(*uart.rng.wifi.base.read_dtb(candidate))
    cases = {
        "UART disabled": ('&uart0 { status = "disabled"; };', "candidate UART0 enabled"),
        "wrong UART address": ('&uart0 { reg = <0 0xfdd51000 0 0x100>; };', "UART0 register range retained"),
        "wrong UART IRQ": ('&uart0 { interrupts = <0 115 4>; };', "UART0 interrupt retained"),
        "wrong UART clock": ('&uart0 { clocks = <&pmucru 12>, <&pmucru 44>; };', "UART0 PMU clock providers and IDs retained"),
        "wrong pin mux": ('&uart0_xfer { rockchip,pins = <0 16 2 &pcfg_pull_up>, <0 17 3 &pcfg_pull_up>; };', "UART0 GPIO0 C0 C1 mux 3 retained"),
        "wrong pin bias": ('&uart0_xfer { rockchip,pins = <0 16 3 &pcfg_pull_none>, <0 17 3 &pcfg_pull_up>; };', "UART0 pull-up config retained"),
        "wrong DMA channel": ('&uart0 { dmas = <&dmac0 2>, <&dmac0 1>; };', "UART0 original DMA references retained"),
        "UART console": ('/ { chosen { bootargs = "console=ttyS0,115200"; }; };', "UART0 not chosen for bootargs"),
        "I2C5 enabled": ('&i2c5 { status = "okay"; };', "I2C5 remains disabled"),
        "unrelated PWM enabled": ('&pwm1 { status = "okay"; };', "only UART0 status property differs"),
        "unrelated RNG disabled": ('&rng { status = "disabled"; };', "only UART0 status property differs"),
    }
    kernel = ROOT / "third_party/linux-rk3588"
    dtc = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc"
    passed = []
    with tempfile.TemporaryDirectory(prefix="uart-faults-", dir=candidate.parent) as directory:
        work = Path(directory)
        for index, (name, (overlay, expected)) in enumerate(cases.items()):
            source = work / (str(index) + ".dts")
            source.write_text('#include "' + str(BOARD / "bsp/rk3568-aiot-3568pq-uart.dts") + '"\n' + overlay + '\n')
            pp = work / (str(index) + ".pp.dts")
            result = subprocess.run(["gcc", "-E", "-P", "-nostdinc", "-undef", "-D__DTS__", "-x", "assembler-with-cpp",
                                     "-I", str(kernel / "arch/arm64/boot/dts/rockchip"),
                                     "-I", str(kernel / "include"), str(source)], capture_output=True, check=True)
            pp.write_bytes(result.stdout)
            dtb = work / (str(index) + ".dtb")
            subprocess.run([str(dtc), "-@", "-I", "dts", "-O", "dtb", "-o", str(dtb), str(pp)], capture_output=True, check=True)
            try:
                uart.audit(*uart.rng.wifi.base.read_dtb(dtb))
            except ValueError as error:
                if expected not in str(error):
                    raise AssertionError("Unexpected rejection: " + name + ": " + str(error)) from error
                passed.append(name)
            else:
                raise AssertionError("Unsafe DTB accepted: " + name)
        try:
            uart.audit(*uart.rng.wifi.base.read_dtb(candidate), candidate)
        except ValueError as error:
            assert "tested RNG baseline SHA locked" in str(error)
            passed.append("wrong baseline identity")
        else:
            raise AssertionError("Wrong baseline accepted")
    print(json.dumps({"status": "UART_REAL_DTB_FAULTS_PASSED", "faults_rejected": len(passed),
                      "passed": passed, "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}, indent=2))


if __name__ == "__main__":
    main()
