#!/usr/bin/env python3
"""Require exactly the tested UART tree plus original RK809 interface wiring."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]
spec = importlib.util.spec_from_file_location("audio_base_uart", BOARD / "verify-uart.py")
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

    def pack(*values):
        return struct.pack(">" + "I" * len(values), *values)

    def handle(path):
        value = tree.get(path + "/phandle", b"")
        check("Valid phandle " + path, len(value) == 4 and int.from_bytes(value, "big") != 0)
        return int.from_bytes(value, "big")

    bus = "/i2s@fe410000"
    codec = "/i2c@fdd40000/pmic@20/codec"
    sound = "/rk809-sound"
    cru = handle("/clock-controller@fdd20000")
    gpio = handle("/pinctrl/gpio4@fe770000")
    pull = handle("/pinctrl/pcfg-pull-none")
    pinroot = "/pinctrl/i2s1/"
    group = lambda name: pinroot + "i2s1m0-" + name
    pins = {name: handle(group(name)) for name in ["mclk", "sclktx", "lrcktx", "sdi0", "sdo0"]}
    codec_handle = handle(codec)
    old_handles = {int.from_bytes(value, "big") for path, value in old.items() if path.endswith("/phandle")}
    check("Codec handle does not collide with original tree", codec_handle not in old_handles)
    all_handles = [int.from_bytes(value, "big") for path, value in tree.items() if path.endswith("/phandle")]
    check("All phandles remain unique", len(all_handles) == len(set(all_handles)))
    replacements = {
        bus + "/status": b"okay\0",
        bus + "/rockchip,clk-trcm": pack(1),
        bus + "/pinctrl-0": pack(*(pins[name] for name in ["sclktx", "lrcktx", "sdi0", "sdo0"])),
    }
    for name, number in [("mclk", 2), ("sclktx", 3), ("lrcktx", 5)]:
        replacements[group(name) + "/rockchip,pins"] = pack(1, number, 1, pull)
    additions = {
        codec + "/#sound-dai-cells": pack(0),
        codec + "/compatible": b"rockchip,rk809-codec\0rockchip,rk817-codec\0",
        codec + "/clocks": pack(cru, 419),
        codec + "/clock-names": b"mclk\0",
        codec + "/assigned-clocks": pack(cru, 419, cru, 422),
        codec + "/assigned-clock-rates": pack(12288000),
        codec + "/assigned-clock-parents": pack(cru, 72, cru, 72),
        codec + "/pinctrl-names": b"default\0",
        codec + "/pinctrl-0": pack(pins["mclk"]),
        codec + "/hp-volume": pack(30),
        codec + "/spk-volume": pack(12),
        codec + "/spk-ctl-gpios": pack(gpio, 20, 1),
        codec + "/mic-in-differential": b"",
        codec + "/status": b"okay\0",
        codec + "/phandle": pack(codec_handle),
        sound + "/status": b"okay\0",
        sound + "/compatible": b"simple-audio-card\0",
        sound + "/simple-audio-card,format": b"i2s\0",
        sound + "/simple-audio-card,name": b"rockchip,rk809-codec\0",
        sound + "/simple-audio-card,mclk-fs": pack(256),
        sound + "/simple-audio-card,cpu/sound-dai": pack(handle(bus)),
        sound + "/simple-audio-card,codec/sound-dai": pack(codec_handle),
        "/__symbols__/rk809_codec": codec.encode() + b"\0",
    }
    for path, value in (replacements | additions).items():
        check("Exact audio property " + path, tree.get(path) == value)
    for name, number in [("mclk", 2), ("sclktx", 3), ("lrcktx", 5), ("sdi0", 11), ("sdo0", 7)]:
        check("Original audio GPIO1 mux/no pull " + name,
              tree.get(group(name) + "/rockchip,pins") == pack(1, number, 1, pull))
    changes = {path for path in old.keys() | tree.keys() if old.get(path) != tree.get(path)}
    check("Only bounded audio properties changed", changes == set(replacements) | set(additions))
    check("No original property removed", set(old).issubset(tree))
    check("Original property order retained", [path for path in tree if path in old] == list(old))
    check("FDT reservations unchanged", reservations == old_reservations)
    normalized = {path: value for path, value in tree.items() if path not in additions}
    for path in replacements:
        if path in old:
            normalized[path] = old[path]
        else:
            del normalized[path]
    inherited = uart.audit(normalized, reservations)
    inherited["checks"] += checks
    inherited.update(variant="wifi-rng-uart0-rk809-audio-interface",
                     checks_passed=len(inherited["checks"]), property_changes=sorted(changes),
                     pcm_open_allowed=False, control_write_allowed=False,
                     audio_hardware_tested=False)
    return inherited


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(*uart.rng.wifi.base.read_dtb(args.dtb)), indent=2))
    except (ValueError, KeyError, OSError, struct.error) as error:
        parser.exit(1, "AUDIO_AUDIT_REJECTED: " + str(error) + "\n")
