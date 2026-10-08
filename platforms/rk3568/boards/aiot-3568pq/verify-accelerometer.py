#!/usr/bin/env python3
"""Audit exact changes against the tested UART DTB, retaining all other bytes."""
import importlib.util
import argparse
import hashlib
import json
from pathlib import Path
import struct
spec = importlib.util.spec_from_file_location("accel_original_uart", Path(__file__).with_name("verify-uart.py"))
uart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uart)


def audit(tree, reservations):
    root = Path(__file__).resolve().parents[4]
    baseline = root / "outputs/rk3568-motor-alignment-20261004/uart.dtb"
    checks = []

    def check(name, condition):
        if not condition:
            raise ValueError(name)
        checks.append(name)

    check("tested UART baseline ordinary file", baseline.is_file() and not baseline.is_symlink())
    check("tested UART SHA locked", hashlib.sha256(baseline.read_bytes()).hexdigest() ==
          "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1")
    old, old_reservations = uart.rng.wifi.base.read_dtb(baseline)
    bus = "/i2c@fe5e0000"
    node = bus + "/mxc6655xa@15"
    irq = "/pinctrl/mxc6655xa/mxc6655xa_irq_gpio"

    def cells(path):
        value = tree.get(path)
        if value is None or len(value) % 4:
            raise ValueError("missing or malformed cells: " + path)
        return list(struct.unpack(">" + "I" * (len(value) // 4), value))

    handles = {cells(path)[0]: path.rsplit("/", 1)[0] for path in tree if path.endswith("/phandle")}
    check("all phandles unique", len(handles) == len([p for p in tree if p.endswith('/phandle')]))
    expected = {
        "compatible": b"gs_mxc6655xa\0", "reg": struct.pack(">I", 0x15), "status": b"okay\0",
        "pinctrl-names": b"default\0", "irq_enable": struct.pack(">I", 0),
        "poll_delay_ms": struct.pack(">I", 30), "type": struct.pack(">I", 2),
        "power-off-in-suspend": struct.pack(">I", 1), "layout": struct.pack(">I", 1)}
    for name, value in expected.items():
        check("accelerometer " + name, tree.get(node + "/" + name) == value)
    check("I2C5 enabled", tree.get(bus + "/status") == b"okay\0")
    pin = cells(bus + "/pinctrl-0")
    check("I2C5 M0 provider", len(pin) == 1 and handles.get(pin[0]) == "/pinctrl/i2c5/i2c5m0-xfer")
    pins = cells("/pinctrl/i2c5/i2c5m0-xfer/rockchip,pins")
    check("I2C5 GPIO3 B3 B4 mux4", len(pins) == 8 and pins[:3] == [3, 11, 4] and pins[4:7] == [3, 12, 4])
    for handle in [pins[3], pins[7]]:
        target = handles.get(handle, "")
        check("I2C5 no pull and schmitt " + str(handle), tree.get(target + "/bias-disable") == b"" and
              tree.get(target + "/input-schmitt-enable") == b"")
    pin = cells(node + "/pinctrl-0")
    check("sensor IRQ pinctrl provider", len(pin) == 1 and handles.get(pin[0]) == irq)
    pins = cells(irq + "/rockchip,pins")
    check("sensor IRQ GPIO3 C1 input mux", len(pins) == 4 and pins[:3] == [3, 17, 0])
    check("sensor IRQ no pull", tree.get(handles.get(pins[3], "") + "/bias-disable") == b"")
    gpio = cells(node + "/irq-gpio")
    check("vendor IRQ GPIO reference retained", len(gpio) == 3 and
          handles.get(gpio[0]) == "/pinctrl/gpio3@fe760000" and gpio[1:] == [17, 8])
    check("new IRQ symbol resolves", tree.get("/__symbols__/mxc6655xa_irq_gpio") == (irq + "\0").encode())
    additions = {node + "/" + name for name in expected} | {
        node + "/pinctrl-0", node + "/irq-gpio", irq + "/phandle", irq + "/rockchip,pins",
        "/__symbols__/mxc6655xa_irq_gpio"}
    changes = {path for path in old.keys() | tree.keys() if old.get(path) != tree.get(path)}
    check("only I2C5 status and bounded sensor additions", changes == additions | {bus + "/status"})
    check("FDT reservations unchanged", reservations == old_reservations)
    normalized = {path: value for path, value in tree.items() if path not in additions}
    normalized[bus + "/status"] = b"disabled\0"
    result = uart.audit(normalized, reservations)
    result["checks"] += checks
    result.update(variant="wifi-rng-uart0-accelerometer", checks_passed=len(result["checks"]),
                  property_changes=sorted(changes), baseline_uart_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
                  sensor_probe_tested=False, sensor_sampling_tested=False, module_unload_tested=False)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(*uart.rng.wifi.base.read_dtb(args.dtb)), indent=2))
    except (ValueError, KeyError, OSError, struct.error) as error:
        parser.exit(1, "ACCEL_AUDIT_REJECTED: " + str(error) + "\n")
