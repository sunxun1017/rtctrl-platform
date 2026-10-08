#!/usr/bin/env python3
"""Reject wrong-controller, voltage, wiring and baseline regressions offline."""
import importlib.util
from pathlib import Path
import struct
import sys

spec = importlib.util.spec_from_file_location('wifi', Path(__file__).with_name('verify-wifi.py'))
wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wifi)
tree, reservations = wifi.base.read_dtb(Path(sys.argv[1]))
wifi.audit(tree, reservations)


def pack(*values):
    return struct.pack('>' + 'I' * len(values), *values)


cases = {
    'SDIO disabled': {'/dwmmc@fe2c0000/status': b'disabled\0'},
    'wrong bus width': {'/dwmmc@fe2c0000/bus-width': pack(8)},
    'guessed voltage rail': {'/dwmmc@fe2c0000/vqmmc-supply': pack(1)},
    'missing SDIO IRQ': {'/dwmmc@fe2c0000/cap-sdio-irq': None},
    'wrong PMIC clock': {'/sdio-pwrseq/clocks': tree['/sdio-pwrseq/clocks'][:4] + pack(0)},
    'reset wrong pin': {'/sdio-pwrseq/reset-gpios': tree['/sdio-pwrseq/reset-gpios'][:4] + pack(10, 1)},
    'reset wrong polarity': {'/sdio-pwrseq/reset-gpios': tree['/sdio-pwrseq/reset-gpios'][:4] + pack(9, 0)},
    'wake wrong polarity': {'/wireless-wlan/WIFI,host_wake_irq': tree['/wireless-wlan/WIFI,host_wake_irq'][:4] + pack(10, 1)},
    'competing reset owner': {'/wireless-wlan/WIFI,reset_gpio': pack(1, 9, 1)},
    'wrong timing': {'/sdio-pwrseq/post-power-on-delay-ms': pack(4)},
    'MCU UART enabled': {'/serial@fdd50000/status': b'okay\0'},
    'lost high reserved RAM': {'/reserved-memory/buffer@1f0000000/no-map': None},
}
for name, changes in cases.items():
    changed = dict(tree)
    for key, value in changes.items():
        if value is None:
            changed.pop(key)
        else:
            changed[key] = value
    try:
        wifi.audit(changed, reservations)
    except ValueError:
        print('REJECTED:', name)
    else:
        raise AssertionError('Unsafe DT mutation accepted: ' + name)
print('WIFI_DT_AUDIT_FAULTS_PASSED', len(cases))
