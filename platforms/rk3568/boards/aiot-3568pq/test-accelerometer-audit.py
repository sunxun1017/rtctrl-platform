#!/usr/bin/env python3
"""Compile malformed accelerator DTBs and exercise the actual property audit."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]
spec = importlib.util.spec_from_file_location("accel_audit", BOARD / "verify-accelerometer.py")
accel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accel)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dtb", type=Path)
    parser.add_argument("preprocessed", type=Path)
    args = parser.parse_args()
    cases = {
        "I2C disabled": '&{/i2c@fe5e0000} { status = "disabled"; };',
        "wrong bus pins": '&{/i2c@fe5e0000} { pinctrl-0 = <&i2c5m1_xfer>; };',
        "wrong address": '&{/i2c@fe5e0000/mxc6655xa@15} { reg = <0x16>; };',
        "wrong compatible": '&{/i2c@fe5e0000/mxc6655xa@15} { compatible = "unknown"; };',
        "IRQ enabled": '&{/i2c@fe5e0000/mxc6655xa@15} { irq_enable = <1>; };',
        "wrong type": '&{/i2c@fe5e0000/mxc6655xa@15} { type = <4>; };',
        "wrong layout": '&{/i2c@fe5e0000/mxc6655xa@15} { layout = <2>; };',
        "wrong poll": '&{/i2c@fe5e0000/mxc6655xa@15} { poll_delay_ms = <1>; };',
        "wrong IRQ pin": '&{/pinctrl/mxc6655xa/mxc6655xa_irq_gpio} { rockchip,pins = <3 18 0 &pcfg_pull_none>; };',
        "IRQ pull changed": '&{/pinctrl/mxc6655xa/mxc6655xa_irq_gpio} { rockchip,pins = <3 17 0 &pcfg_pull_up>; };',
        "MCU unexpectedly added": '&{/i2c@fe5e0000} { mcu@62 { compatible = "smdtmcu,STM8S00K3"; reg = <0x62>; }; };',
        "unrelated UART changed": '&uart0 { status = "disabled"; };',
        "unrelated PWM enabled": '&pwm1 { status = "okay"; };',
    }
    passed = []
    dtc = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc"
    with tempfile.TemporaryDirectory(prefix="accel-dtb-faults-") as directory:
        work = Path(directory)
        for index, (name, overlay) in enumerate(cases.items()):
            source = work / f"{index}.dts"
            source.write_bytes(args.preprocessed.read_bytes() + overlay.encode() + b"\n")
            dtb = work / f"{index}.dtb"
            subprocess.run([str(dtc), "-@", "-I", "dts", "-O", "dtb", "-o", str(dtb), str(source)],
                           capture_output=True, check=True)
            try:
                accel.audit(*accel.uart.rng.wifi.base.read_dtb(dtb))
            except ValueError:
                passed.append(name)
            else:
                raise AssertionError("Unsafe candidate accepted: " + name)
    result = accel.audit(*accel.uart.rng.wifi.base.read_dtb(args.dtb))
    print(json.dumps({"status": "ACCEL_REAL_DTB_FAULTS_PASSED", "faults_rejected": len(passed),
                      "passed": passed, "candidate_checks": result["checks_passed"]}, indent=2))


if __name__ == "__main__":
    main()
