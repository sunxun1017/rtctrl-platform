#!/usr/bin/env python3
"""Reject genuinely compiled audio trees with wrong or unrelated changes."""
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
    parser.add_argument("--audit-script", type=Path, default=BOARD / "verify-audio.py")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("audio_audit", args.audit_script)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    codec = "&{/i2c@fdd40000/pmic@20/codec}"
    sound = "&{/rk809-sound}"
    cases = {
        "I2S disabled": '&i2s1_8ch { status = "disabled"; };',
        "independent RX clock": '&i2s1_8ch { rockchip,clk-trcm = <0>; };',
        "extra audio pin": '&i2s1_8ch { pinctrl-0 = <&i2s1m0_sclktx &i2s1m0_lrcktx &i2s1m0_sdi0 &i2s1m0_sdo0 &i2s1m0_sdi1>; };',
        "missing codec fallback": codec + ' { compatible = "rockchip,rk809-codec"; };',
        "codec disabled": codec + ' { status = "disabled"; };',
        "wrong clock": codec + ' { clocks = <&cru 420>; };',
        "wrong initial rate": codec + ' { assigned-clock-rates = <24576000>; };',
        "wrong clock parents": codec + ' { assigned-clock-parents = <&cru 76 &cru 76>; };',
        "wrong MCLK pin": codec + ' { pinctrl-0 = <&i2s1m1_mclk>; };',
        "speaker wrong polarity": codec + ' { spk-ctl-gpios = <&gpio4 20 0>; };',
        "speaker wrong pin": codec + ' { spk-ctl-gpios = <&gpio4 21 1>; };',
        "wrong hp volume": codec + ' { hp-volume = <20>; };',
        "differential missing": codec + ' { /delete-property/ mic-in-differential; };',
        "extra headphone GPIO": codec + ' { hp-ctl-gpios = <&gpio4 21 0>; };',
        "old unsupported DAPM route": sound + ' { simple-audio-card,routing = "Headphone Jack", "HPOL"; };',
        "wrong card identity": sound + ' { simple-audio-card,name = "other-card"; };',
        "wrong serial format": sound + ' { simple-audio-card,format = "left_j"; };',
        "wrong mclk ratio": sound + ' { simple-audio-card,mclk-fs = <128>; };',
        "wrong CPU DAI": '&{/rk809-sound/simple-audio-card,cpu} { sound-dai = <&i2s0_8ch>; };',
        "wrong codec DAI": '&{/rk809-sound/simple-audio-card,codec} { sound-dai = <&i2s1_8ch>; };',
        "unrelated UART disabled": '&uart0 { status = "disabled"; };',
        "unrelated sensor enabled": '&i2c5 { status = "okay"; };',
        "unrelated SPI enabled": '&spi3 { status = "okay"; };',
    }
    audit.audit(*audit.uart.rng.wifi.base.read_dtb(args.dtb))
    dtc = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc"
    passed = []
    with tempfile.TemporaryDirectory(prefix="audio-faults-", dir=args.dtb.parent) as directory:
        work = Path(directory)
        for index, (name, overlay) in enumerate(cases.items()):
            source = work / (str(index) + ".dts")
            source.write_bytes(args.preprocessed.read_bytes() + overlay.encode() + b"\n")
            candidate = work / (str(index) + ".dtb")
            subprocess.run([str(dtc), "-@", "-I", "dts", "-O", "dtb", "-o", str(candidate), str(source)],
                           capture_output=True, check=True)
            try:
                audit.audit(*audit.uart.rng.wifi.base.read_dtb(candidate))
            except ValueError:
                passed.append(name)
            else:
                raise AssertionError("Invalid compiled DTB accepted: " + name)
    print(json.dumps({"status": "AUDIO_REAL_DTB_FAULTS_PASSED", "faults_rejected": len(passed),
                      "passed": passed}, indent=2))


if __name__ == "__main__":
    main()
