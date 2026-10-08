#!/usr/bin/env python3
"""Require the original Wi-Fi audit and exactly one semantic RNG status change."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]
BASELINE = ROOT / "outputs/rk3568-source-wifi-20261004/build/dtb-v3/rk3568-aiot-3568pq-wifi.dtb"
BASELINE_SHA = "3341cf513036528aaa0abd3b6c1fd0bc55cdb1dafe8b667c8431c03ae3b7d383"
RNG = "/rng@fe388000"
CRU = "/clock-controller@fdd20000"

spec = importlib.util.spec_from_file_location("wifi_rng_original_wifi", BOARD / "verify-wifi.py")
wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wifi)


def audit(tree, reservations, baseline=BASELINE):
    checks = []

    def check(name, condition):
        if not condition:
            raise ValueError(name)
        checks.append(name)

    baseline = Path(baseline)
    check("original Wi-Fi baseline is an ordinary file", baseline.is_file() and not baseline.is_symlink())
    check("original Wi-Fi DTB SHA locked", hashlib.sha256(baseline.read_bytes()).hexdigest() == BASELINE_SHA)
    old_tree, old_reservations = wifi.base.read_dtb(baseline)
    result = wifi.audit(tree, reservations)

    def cells(path):
        value = tree.get(path)
        if value is None or len(value) % 4:
            raise ValueError("missing or malformed RNG/provider cells: " + path)
        return list(struct.unpack(">" + "I" * (len(value) // 4), value))

    handles = {cells(path)[0]: path.rsplit("/", 1)[0] for path in tree if path.endswith("/phandle")}
    check("original RNG status disabled", old_tree.get(RNG + "/status") == b"disabled\0")
    check("candidate RNG status enabled", tree.get(RNG + "/status") == b"okay\0")
    check("RK3568 crypto-v2 RNG compatible", tree.get(RNG + "/compatible") == b"rockchip,cryptov2-rng\0")
    check("RNG register range retained", cells(RNG + "/reg") == [0, 0xfe388000, 0, 0x2000])
    clocks = cells(RNG + "/clocks")
    check("RNG clocks reference original CRU IDs",
          len(clocks) == 4 and handles.get(clocks[0]) == CRU and clocks[1] == 112
          and handles.get(clocks[2]) == CRU and clocks[3] == 111)
    check("RNG clock provider cell width", cells(CRU + "/#clock-cells") == [1])
    check("RNG clock names retained", tree.get(RNG + "/clock-names") == b"clk_trng\0hclk_trng\0")
    reset = cells(RNG + "/resets")
    check("RNG reset references original CRU ID", len(reset) == 2 and handles.get(reset[0]) == CRU and reset[1] == 109)
    check("RNG reset provider cell width", cells(CRU + "/#reset-cells") == [1])
    check("RNG reset name retained", tree.get(RNG + "/reset-names") == b"reset\0")
    changes = sorted(path for path in set(old_tree) | set(tree) if old_tree.get(path) != tree.get(path))
    check("only RNG status property differs", changes == [RNG + "/status"])
    check("FDT reservation list unchanged", reservations == old_reservations)
    result["checks"] += checks
    result["checks_passed"] = len(result["checks"])
    result["variant"] = "wifi-rng"
    result["baseline_dtb_sha256"] = BASELINE_SHA
    result["property_changes"] = changes
    result["rng_driver_bound"] = False
    result["entropy_initialized_tested"] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(*wifi.base.read_dtb(args.dtb), args.baseline), indent=2))
    except (ValueError, KeyError, OSError, struct.error) as error:
        parser.exit(1, "WIFI_RNG_AUDIT_REJECTED: " + str(error) + "\n")


if __name__ == "__main__":
    main()
