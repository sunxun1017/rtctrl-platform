#!/usr/bin/env python3
"""Require the tested UART/RNG tree plus a fixed SPI3 identity-only endpoint."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]
spec = importlib.util.spec_from_file_location("cap_base_uart", BOARD / "verify-uart.py")
uart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uart)


def audit(tree, reservations):
    baseline = ROOT / "outputs/rk3568-motor-alignment-20261004/uart.dtb"
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1":
        raise ValueError("Tested UART baseline changed")
    old, old_reservations = uart.rng.wifi.base.read_dtb(baseline)
    checks = []

    def check(label, condition):
        if not condition:
            raise ValueError(label)
        checks.append(label)

    def cells(path):
        value = tree.get(path, b"")
        if len(value) % 4:
            raise ValueError("Malformed cells: " + path)
        return list(struct.unpack(">" + "I" * (len(value) // 4), value))

    handles = {int.from_bytes(value, "big"): path.rsplit("/", 1)[0]
               for path, value in tree.items() if path.endswith("/phandle") and len(value) == 4}
    bus = "/spi@fe640000"
    node = bus + "/cap1188@0"
    check("SPI3 enabled", tree.get(bus + "/status") == b"okay\0")
    check("Only one CS supported", cells(bus + "/num-cs") == [1])
    expected = {
        "compatible": b"rockchip,spidev\0", "status": b"okay\0",
        "reg": bytes(4), "spi-max-frequency": (100000).to_bytes(4, "big"),
        "spi-cpha": b"", "spi-cpol": b"",
    }
    for name, value in expected.items():
        check("Diagnostic endpoint " + name, tree.get(node + "/" + name) == value)
    cs = "/pinctrl/spi3/spi3m1-cs0"
    normal = "/pinctrl/spi3/spi3m1-pins"
    high = "/pinctrl/spi3-hs/spi3m1-pins"
    check("Default M1 CS0 and bus only", [handles.get(value) for value in cells(bus + "/pinctrl-0")] == [cs, normal])
    check("High-speed M1 CS0 and bus only", [handles.get(value) for value in cells(bus + "/pinctrl-1")] == [cs, high])
    cs_pins = cells(cs + "/rockchip,pins")
    check("CS0 GPIO4 C6 mux2", len(cs_pins) == 4 and cs_pins[:3] == [4, 22, 2])
    check("CS0 no internal pull", tree.get(handles.get(cs_pins[3], "") + "/bias-disable") == b"")
    for label, path, high_speed in [("default", normal, False), ("high speed", high, True)]:
        pins = cells(path + "/rockchip,pins")
        check(label + " CLK MISO MOSI pins", len(pins) == 12 and [pins[i:i+3] for i in [0, 4, 8]] ==
              [[4, 18, 2], [4, 21, 2], [4, 19, 2]])
        for value in pins[3::4]:
            config = handles.get(value, "")
            if high_speed:
                check(label + " original pull/drive", tree.get(config + "/bias-pull-up") == b""
                      and tree.get(config + "/drive-strength") == (1).to_bytes(4, "big"))
            else:
                check(label + " no internal pull", tree.get(config + "/bias-disable") == b"")
    changes = {path for path in old.keys() | tree.keys() if old.get(path) != tree.get(path)}
    additions = {node + "/" + name for name in expected}
    replacements = {bus + "/status", bus + "/num-cs", bus + "/pinctrl-0", bus + "/pinctrl-1"}
    check("Only bounded SPI endpoint and bus properties changed", changes == additions | replacements)
    check("No original property removed", set(old).issubset(tree))
    check("Original property order retained", [path for path in tree if path in old] == list(old))
    check("FDT reservations unchanged", reservations == old_reservations)
    normalized = {path: value for path, value in tree.items() if path not in additions}
    for path in replacements:
        normalized[path] = old[path]
    inherited = uart.audit(normalized, reservations)
    inherited["checks"] += checks
    inherited.update(variant="wifi-rng-uart0-cap1188-spi-identity",
                     checks_passed=len(inherited["checks"]), property_changes=sorted(changes),
                     reset_gpio_requested=False, input_driver_registered=False,
                     sensor_identity_hardware_tested=False)
    return inherited


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(*uart.rng.wifi.base.read_dtb(args.dtb)), indent=2))
    except (ValueError, KeyError, OSError, struct.error) as error:
        parser.exit(1, "CAP_SPI_AUDIT_REJECTED: " + str(error) + "\n")
