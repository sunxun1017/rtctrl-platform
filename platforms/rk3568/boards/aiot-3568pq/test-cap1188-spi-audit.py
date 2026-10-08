#!/usr/bin/env python3
"""Compile wrong SPI diagnostic candidates and require real audit rejection."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("preprocessed", type=Path)
    parser.add_argument("--audit-script", type=Path, default=BOARD / "verify-cap1188-spi.py")
    args = parser.parse_args()
    script = args.audit_script.resolve(strict=True)
    script.relative_to(ROOT)
    spec = importlib.util.spec_from_file_location("cap_audit", script)
    auditor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auditor)
    cases = {
        "SPI disabled": '&spi3 { status = "disabled"; };',
        "default M0 pins": '&spi3 { pinctrl-0 = <&spi3m0_cs0 &spi3m0_pins>; };',
        "high speed M0 pins": '&spi3 { pinctrl-1 = <&spi3m0_cs0 &spi3m0_pins_hs>; };',
        "unexpected CS1": '&spi3 { pinctrl-0 = <&spi3m1_cs0 &spi3m1_cs1 &spi3m1_pins>; };',
        "two CS": '&spi3 { num-cs = <2>; };',
        "wrong address": '&{/spi@fe640000/cap1188@0} { reg = <1>; };',
        "wrong speed": '&{/spi@fe640000/cap1188@0} { spi-max-frequency = <1000000>; };',
        "wrong mode": '&{/spi@fe640000/cap1188@0} { /delete-property/ spi-cpha; };',
        "wrong compatible": '&{/spi@fe640000/cap1188@0} { compatible = "microchip,cap1188"; };',
        "reset unexpectedly driven": '&{/spi@fe640000/cap1188@0} { reset-gpios = <&gpio0 14 0>; };',
        "wrong bus GPIO": '&spi3m1_pins { rockchip,pins = <4 18 3 &pcfg_pull_none>, <4 21 2 &pcfg_pull_none>, <4 19 2 &pcfg_pull_none>; };',
        "wrong high speed pull": '&spi3m1_pins_hs { rockchip,pins = <4 18 2 &pcfg_pull_none>, <4 21 2 &pcfg_pull_none>, <4 19 2 &pcfg_pull_none>; };',
        "extra SPI child": '&spi3 { unknown@1 { compatible = "rockchip,spidev"; reg = <1>; spi-max-frequency = <100000>; }; };',
        "unrelated UART disabled": '&uart0 { status = "disabled"; };',
        "unrelated sensor enabled": '&i2c5 { status = "okay"; };',
    }
    auditor.audit(*auditor.uart.rng.wifi.base.read_dtb(args.dtb))
    dtc = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc"
    passed = []
    with tempfile.TemporaryDirectory(prefix="cap-spi-faults-", dir=args.dtb.parent) as directory:
        work = Path(directory)
        for index, (name, overlay) in enumerate(cases.items()):
            source = work / (str(index) + ".dts")
            source.write_bytes(args.preprocessed.read_bytes() + overlay.encode() + b"\n")
            candidate = work / (str(index) + ".dtb")
            subprocess.run([str(dtc), "-@", "-I", "dts", "-O", "dtb", "-o", str(candidate), str(source)],
                           capture_output=True, check=True)
            try:
                auditor.audit(*auditor.uart.rng.wifi.base.read_dtb(candidate))
            except ValueError:
                passed.append(name)
            else:
                raise AssertionError("Invalid compiled DTB accepted: " + name)
    print(json.dumps({"status": "CAP_SPI_REAL_DTB_FAULTS_PASSED", "faults_rejected": len(passed),
                      "passed": passed}, indent=2))


if __name__ == "__main__":
    main()
