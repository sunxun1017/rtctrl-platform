#!/usr/bin/env python3
"""Require the tested RNG DT plus exactly the UART0 enable property."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]
BASELINE = ROOT / "outputs/rk3568-rng-network-20261004/wifi-rng.dtb"
BASELINE_SHA = "ab0893cea485cb9972d93dfb3eaa61ec955cbf4314a3f0f39c43b418249e8035"
UART = "/serial@fdd50000"
PMUCRU = "/clock-controller@fdd00000"
DMAC = "/dmac@fe530000"
I2C5 = "/i2c@fe5e0000"

spec = importlib.util.spec_from_file_location("uart_original_rng", BOARD / "verify-wifi-rng.py")
rng = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rng)


def audit(tree, reservations, baseline=BASELINE):
    checks = []

    def check(name, condition):
        if not condition:
            raise ValueError(name)
        checks.append(name)

    baseline = Path(baseline)
    check("tested RNG baseline is an ordinary file", baseline.is_file() and not baseline.is_symlink())
    check("tested RNG baseline SHA locked", hashlib.sha256(baseline.read_bytes()).hexdigest() == BASELINE_SHA)
    old_tree, old_reservations = rng.wifi.base.read_dtb(baseline)

    def cells(path):
        value = tree.get(path)
        if value is None or len(value) % 4:
            raise ValueError("missing or malformed UART/provider cells: " + path)
        return list(struct.unpack(">" + "I" * (len(value) // 4), value))

    handles = {cells(path)[0]: path.rsplit("/", 1)[0] for path in tree if path.endswith("/phandle")}
    check("original UART0 disabled", old_tree.get(UART + "/status") == b"disabled\0")
    check("candidate UART0 enabled", tree.get(UART + "/status") == b"okay\0")
    check("UART0 compatible retained", tree.get(UART + "/compatible") == b"rockchip,rk3568-uart\0snps,dw-apb-uart\0")
    check("UART0 register range retained", cells(UART + "/reg") == [0, 0xfdd50000, 0, 0x100])
    check("UART0 interrupt retained", cells(UART + "/interrupts") == [0, 116, 4])
    clocks = cells(UART + "/clocks")
    check("UART0 PMU clock providers and IDs retained", len(clocks) == 4
          and handles.get(clocks[0]) == PMUCRU and clocks[1] == 11
          and handles.get(clocks[2]) == PMUCRU and clocks[3] == 44)
    check("UART0 clock names retained", tree.get(UART + "/clock-names") == b"baudclk\0apb_pclk\0")
    check("UART0 register widths retained", cells(UART + "/reg-shift") == [2]
          and cells(UART + "/reg-io-width") == [4])
    check("serial0 alias selects UART0", tree.get("/aliases/serial0") == (UART + "\0").encode())
    pinctrl = cells(UART + "/pinctrl-0")
    check("UART0 pinctrl group retained", len(pinctrl) == 1
          and handles.get(pinctrl[0]) == "/pinctrl/uart0/uart0-xfer")
    pins = cells(handles[pinctrl[0]] + "/rockchip,pins")
    check("UART0 GPIO0 C0 C1 mux 3 retained", len(pins) == 8
          and pins[:3] == [0, 16, 3] and pins[4:7] == [0, 17, 3])
    check("UART0 pull-up config retained", all(tree.get(handles.get(handle, "") + "/bias-pull-up") == b""
          for handle in [pins[3], pins[7]]))
    dmas = cells(UART + "/dmas")
    check("UART0 original DMA references retained", len(dmas) == 4
          and handles.get(dmas[0]) == DMAC and dmas[1] == 0
          and handles.get(dmas[2]) == DMAC and dmas[3] == 1)
    check("UART0 DMA names not invented", UART + "/dma-names" not in tree)
    check("I2C5 remains disabled", tree.get(I2C5 + "/status") == b"disabled\0")
    check("power MCU node remains absent", not any(path.startswith(I2C5 + "/mcu@")
          or b"smdtmcu" in value for path, value in tree.items() if path.endswith("/compatible")))
    for property_name in ["bootargs", "stdout-path", "linux,stdout-path"]:
        value = tree.get("/chosen/" + property_name, b"")
        check("UART0 not chosen for " + property_name, b"ttyS0" not in value
              and b"ttySMT0" not in value and UART.encode() not in value and b"serial0" not in value)
    changes = sorted(path for path in set(old_tree) | set(tree) if old_tree.get(path) != tree.get(path))
    check("only UART0 status property differs", changes == [UART + "/status"])
    check("FDT reservations unchanged", reservations == old_reservations)
    normalized = dict(tree)
    normalized[UART + "/status"] = b"disabled\0"
    result = rng.audit(normalized, reservations)
    result["checks"] += checks
    result.update(variant="wifi-rng-uart0", checks_passed=len(result["checks"]),
                  baseline_dtb_sha256=BASELINE_SHA, property_changes=changes,
                  uart_driver_binding_tested=False, physical_motor_tested=False,
                  stop_or_disable_semantics_verified=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(*rng.wifi.base.read_dtb(args.dtb), args.baseline), indent=2))
    except (ValueError, KeyError, OSError, struct.error) as error:
        parser.exit(1, "UART_AUDIT_REJECTED: " + str(error) + "\n")


if __name__ == "__main__":
    main()
