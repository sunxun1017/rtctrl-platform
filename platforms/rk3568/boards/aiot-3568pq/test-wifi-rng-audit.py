#!/usr/bin/env python3
"""Compile real DTB faults and require the RNG/Wi-Fi auditor to reject them."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]
spec = importlib.util.spec_from_file_location("wifi_rng", BOARD / "verify-wifi-rng.py")
rng = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rng)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("--dtc", type=Path, default=ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc")
    args = parser.parse_args()
    candidate = args.dtb.resolve(strict=True)
    rng.audit(*rng.wifi.base.read_dtb(candidate))
    kernel = ROOT / "third_party/linux-rk3588"
    cases = {
        "RNG disabled": ('&rng { status = "disabled"; };\n', "candidate RNG status enabled"),
        "wrong RNG register range": ("&rng { reg = <0 0xfe388000 0 0x1000>; };\n", "RNG register range retained"),
        "wrong RNG clock ID": ("&rng { clocks = <&cru 113>, <&cru 111>; };\n", "RNG clocks reference original CRU IDs"),
        "wrong RNG clock provider": ("&rng { clocks = <&pmucru 112>, <&cru 111>; };\n", "RNG clocks reference original CRU IDs"),
        "wrong RNG reset ID": ("&rng { resets = <&cru 110>; };\n", "RNG reset references original CRU ID"),
        "wrong RNG reset provider": ("&rng { resets = <&pmucru 109>; };\n", "RNG reset references original CRU ID"),
        "wrong RNG compatible": ('&rng { compatible = "rockchip,cryptov1-rng"; };\n', "RK3568 crypto-v2 RNG compatible"),
        "wrong RNG clock names": ('&rng { clock-names = "clk_wrong", "hclk_trng"; };\n', "RNG clock names retained"),
        "unrelated model change": ('/ { model = "unapproved model change"; };\n', "only RNG status property differs"),
        "unrelated crypto node change": ('&crypto { status = "okay"; };\n', "only RNG status property differs"),
    }
    passed = []
    with tempfile.TemporaryDirectory(prefix="rng-faults-", dir=candidate.parent) as temporary:
        work = Path(temporary)
        for index, (name, (overlay, expected)) in enumerate(cases.items()):
            dts = work / ("fault-" + str(index) + ".dts")
            dts.write_text('#include "' + str(BOARD / "bsp/rk3568-aiot-3568pq-wifi-rng.dts") + '"\n' + overlay)
            preprocessed = subprocess.run([
                "/usr/bin/gcc", "-E", "-P", "-nostdinc", "-undef", "-D__DTS__", "-x", "assembler-with-cpp",
                "-I", str(kernel / "arch/arm64/boot/dts/rockchip"), "-I", str(kernel / "include"), str(dts),
            ], capture_output=True, check=True)
            pp = work / ("fault-" + str(index) + ".pp.dts")
            pp.write_bytes(preprocessed.stdout)
            dtb = work / ("fault-" + str(index) + ".dtb")
            subprocess.run([str(args.dtc), "-@", "-I", "dts", "-O", "dtb", "-o", str(dtb), str(pp)],
                           capture_output=True, check=True)
            try:
                rng.audit(*rng.wifi.base.read_dtb(dtb))
            except ValueError as error:
                if expected not in str(error):
                    raise AssertionError("Unexpected fault rejection: " + name + ": " + str(error)) from error
                passed.append(name)
            else:
                raise AssertionError("Unsafe real DTB accepted: " + name)
        # The candidate is a valid DTB but cannot substitute for the locked baseline.
        try:
            rng.audit(*rng.wifi.base.read_dtb(candidate), candidate)
        except ValueError as error:
            assert "original Wi-Fi DTB SHA locked" in str(error)
            passed.append("wrong original baseline SHA")
        else:
            raise AssertionError("Changed baseline identity accepted")
    print(json.dumps({"status": "WIFI_RNG_REAL_DTB_FAULTS_PASSED", "faults_rejected": len(passed),
                      "passed": passed, "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                      "board_tested": False}, indent=2))


if __name__ == "__main__":
    main()
