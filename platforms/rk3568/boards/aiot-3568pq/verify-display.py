#!/usr/bin/env python3
"""Require the locked UART tree plus exactly the original panel display wiring."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]
BASELINE = ROOT / "outputs/rk3568-motor-alignment-20261004/uart.dtb"
BASELINE_SHA = "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1"
ANDROID = ROOT / "outputs/android-board-20260928/live-sorted.dtb"
ANDROID_SHA = "fe3c9f3138a755110506dc77881d0cb543cd5c128d50475369adf5af5c29611b"
INIT_SHA = "2457eb606192208499fb71d3e9e91cd5b6a17a2c3da9c38bc6d79cc08b81966d"
BRIGHTNESS_SHA = "9bf3050f5f80dae9ca4f382a65f16fa2f4d9eb31be72e18f8c05e2f0af99f6dd"
spec = importlib.util.spec_from_file_location("display_base_uart", BOARD / "verify-uart.py")
uart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uart)


def audit(tree, reservations):
    checks = []

    def check(label, condition):
        if not condition:
            raise ValueError(label)
        checks.append(label)

    def pack(*values):
        return struct.pack(">" + "I" * len(values), *values)

    def cells(path):
        value = tree.get(path)
        check("Well-formed cells " + path, value is not None and len(value) % 4 == 0)
        return list(struct.unpack(">" + "I" * (len(value) // 4), value))

    def handle(path):
        values = cells(path + "/phandle")
        check("Valid phandle " + path, len(values) == 1 and 0 < values[0] < 0xffffffff)
        return values[0]

    check("Tested UART baseline SHA locked", BASELINE.is_file() and not BASELINE.is_symlink()
          and hashlib.sha256(BASELINE.read_bytes()).hexdigest() == BASELINE_SHA)
    check("Android display evidence SHA locked", ANDROID.is_file() and not ANDROID.is_symlink()
          and hashlib.sha256(ANDROID.read_bytes()).hexdigest() == ANDROID_SHA)
    old, old_reservations = uart.rng.wifi.base.read_dtb(BASELINE)
    original, _ = uart.rng.wifi.base.read_dtb(ANDROID)
    panel = "/dsi@fe060000/panel@0"
    timing = panel + "/display-timings/timing0"
    panel_input = panel + "/port/endpoint"
    dsi_output = "/dsi@fe060000/ports/port@1/endpoint"
    supply = "/vcc3v3-lcd0-n"
    backlight = "/backlight"
    gpio0 = handle("/pinctrl/gpio0@fdd60000")
    pwm4 = handle("/pwm@fe6e0000")
    supply_input = handle("/vcc3v3-sys")
    new_nodes = [panel, timing, panel_input, dsi_output, supply, backlight]
    new_handles = {path: handle(path) for path in new_nodes}
    old_handles = {int.from_bytes(value, "big") for path, value in old.items() if path.endswith("/phandle")}
    check("All new phandles are above the original maximum",
          all(value > max(old_handles) for value in new_handles.values()))
    phandles = [value for path, value in tree.items() if path.endswith("/phandle")]
    check("All phandle cells valid", all(len(value) == 4 and 0 < int.from_bytes(value, "big") < 0xffffffff
          for value in phandles))
    all_handles = [int.from_bytes(value, "big") for value in phandles]
    check("All phandles are unique", len(all_handles) == len(set(all_handles)))
    check("All original phandles retained", all(tree.get(path) == value
          for path, value in old.items() if path.endswith("/phandle")))

    # Identity, polarity, delays and mode are literal board evidence. The complete
    # sequences/table are compared to a separately locked capture, never the DTS.
    init = original[panel + "/panel-init-sequence"]
    levels = original[backlight + "/brightness-levels"]
    check("Original init sequence identity", len(init) == 898 and hashlib.sha256(init).hexdigest() == INIT_SHA)
    check("Original brightness table identity", len(levels) == 1024
          and hashlib.sha256(levels).hexdigest() == BRIGHTNESS_SHA)
    replacements = {path + "/status": b"okay\0" for path in [
        "/display-subsystem", "/vop@fe040000", "/iommu@fe043e00", "/phy@fe850000",
        "/dsi@fe060000", "/pwm@fe6e0000", "/dsi@fe060000/ports/port@0/endpoint@1"]}
    removals = {"/display-subsystem/memory-region", "/display-subsystem/memory-region-names"}
    additions = {
        supply + "/compatible": b"regulator-fixed\0",
        supply + "/regulator-name": b"vcc3v3_lcd0_n\0",
        supply + "/regulator-min-microvolt": pack(3300000),
        supply + "/regulator-max-microvolt": pack(3300000),
        supply + "/regulator-boot-on": b"",
        supply + "/vin-supply": pack(supply_input),
        supply + "/enable-active-high": b"",
        supply + "/status": b"okay\0",
        supply + "/regulator-state-mem/regulator-off-in-suspend": b"",
        backlight + "/compatible": b"pwm-backlight\0",
        backlight + "/pwms": pack(pwm4, 0, 25000, 0),
        backlight + "/brightness-levels": levels,
        backlight + "/default-brightness-level": pack(0),
        "/dsi@fe060000/ports/port@1/reg": pack(1),
        dsi_output + "/remote-endpoint": pack(new_handles[panel_input]),
        panel + "/compatible": b"simple-panel-dsi\0",
        panel + "/reg": pack(0),
        panel + "/status": b"okay\0",
        panel + "/power-supply": pack(new_handles[supply]),
        panel + "/backlight": pack(new_handles[backlight]),
        panel + "/reset-gpios": pack(gpio0, 5, 1),
        panel + "/enable-gpios": pack(gpio0, 21, 0),
        panel + "/prepare-delay-ms": pack(50),
        panel + "/reset-delay-ms": pack(120),
        panel + "/init-delay-ms": pack(120),
        panel + "/enable-delay-ms": pack(220),
        panel + "/disable-delay-ms": pack(120),
        panel + "/unprepare-delay-ms": pack(120),
        panel + "/screen-type": pack(2),
        panel + "/dsi,lanes": pack(4),
        panel + "/dsi,format": pack(0),
        panel + "/dsi,flags": pack(0xa03),
        panel + "/panel-init-sequence": init,
        panel + "/panel-exit-sequence": bytes.fromhex("05 00 01 28 05 00 01 10"),
        panel_input + "/remote-endpoint": pack(new_handles[dsi_output]),
        panel + "/display-timings/native-mode": pack(new_handles[timing]),
    }
    for name, value in {
        "clock-frequency": 35500000, "hactive": 720, "hfront-porch": 24,
        "hsync-len": 2, "hback-porch": 30, "vactive": 720, "vfront-porch": 16,
        "vsync-len": 2, "vback-porch": 8, "hsync-active": 0, "vsync-active": 0,
        "de-active": 0, "pixelclk-active": 0,
    }.items():
        additions[timing + "/" + name] = pack(value)
    for path, value in new_handles.items():
        additions[path + "/phandle"] = pack(value)
    for label, path in {
        "vcc3v3_lcd0_n": supply, "backlight": backlight, "dsi0_out": dsi_output,
        "dsi0_panel": panel, "panel_in_dsi": panel_input, "dsi0_timing": timing,
    }.items():
        additions["/__symbols__/" + label] = path.encode() + b"\0"
    for path, value in (replacements | additions).items():
        check("Exact display property " + path, tree.get(path) == value)
    for path in removals:
        check("Loader display memory mapping removed " + path, path not in tree)
    for route in ["dsi0", "dsi1", "edp", "hdmi", "lvds", "rgb"]:
        check("Loader logo route disabled " + route,
              tree.get("/display-subsystem/route/route-" + route + "/status") == b"disabled\0")
    check("DSI VP0 input disabled", tree.get("/dsi@fe060000/ports/port@0/endpoint@0/status") == b"disabled\0")
    check("VP1 to DSI input references retained",
          tree.get("/vop@fe040000/ports/port@1/endpoint@0/remote-endpoint") == pack(handle("/dsi@fe060000/ports/port@0/endpoint@1"))
          and tree.get("/dsi@fe060000/ports/port@0/endpoint@1/remote-endpoint") == pack(handle("/vop@fe040000/ports/port@1/endpoint@0")))
    check("PWM4 GPIO0 C3 mux1 no pull retained",
          cells("/pinctrl/pwm4/pwm4-pins/rockchip,pins") == [0, 19, 1, handle("/pinctrl/pcfg-pull-none")])
    check("No invented regulator or backlight GPIO", all(path not in tree for path in [
        supply + "/gpio", supply + "/gpios", backlight + "/enable-gpios"]))

    def command_summary(path):
        data = tree.get(path, b"")
        commands, offset, delay = [], 0, 0
        while offset < len(data):
            if len(data) - offset < 3:
                raise ValueError("Incomplete command header " + path)
            kind, wait, size = data[offset:offset + 3]
            if size == 0 or offset + 3 + size > len(data):
                raise ValueError("Incomplete or empty command payload " + path)
            if not ((kind == 0x13 and size == 2) or (kind == 0x05 and size == 1)):
                raise ValueError("Unsupported command type or length " + path)
            commands.append(data[offset:offset + 3 + size])
            delay += wait
            offset += size + 3
        check("All command records well-formed " + path, offset == len(data))
        return commands, delay

    init_commands, init_delay = command_summary(panel + "/panel-init-sequence")
    exit_commands, exit_delay = command_summary(panel + "/panel-exit-sequence")
    check("180 original init commands and 596ms encoded delay", len(init_commands) == 180 and init_delay == 596)
    check("Sleep out then display on with 120ms each", init_commands[-2:] == [
        bytes.fromhex("05 78 01 11"), bytes.fromhex("05 78 01 29")])
    check("Display off then sleep in without invented exit delay", exit_commands == [
        bytes.fromhex("05 00 01 28"), bytes.fromhex("05 00 01 10")] and exit_delay == 0)
    check("Zero initial brightness with original low and maximum duty", int.from_bytes(levels[:4], "big") == 0
          and int.from_bytes(levels[128:132], "big") == 35
          and int.from_bytes(levels[-4:], "big") == 255)
    changes = {path for path in old.keys() | tree.keys() if old.get(path) != tree.get(path)}
    check("Only bounded display properties changed", changes == set(replacements) | set(additions) | removals)
    check("Only loader display mapping properties removed", set(old) - set(tree) == removals)
    check("Original retained property order preserved", [path for path in tree if path in old] == [path for path in old if path not in removals])
    check("FDT reservations unchanged", reservations == old_reservations)
    normalized = {path: old[path] if path in replacements or path in removals else tree[path] for path in old}
    inherited = uart.audit(normalized, reservations)
    inherited["checks"] += checks
    inherited.update(
        variant="wifi-rng-uart0-vp1-dsi0-original-720x720-display",
        checks_passed=len(inherited["checks"]), property_changes=sorted(changes),
        removed_properties=sorted(removals), baseline_uart_dtb_sha256=BASELINE_SHA,
        android_evidence_dtb_sha256=ANDROID_SHA, init_sequence_sha256=INIT_SHA,
        init_sequence_bytes=len(init), init_sequence_commands=len(init_commands),
        init_sequence_delay_ms=init_delay, exit_sequence_hex="05 00 01 28 05 00 01 10",
        brightness_table_sha256=BRIGHTNESS_SHA, brightness_table_entries=256,
        default_brightness_index=0, default_brightness_duty=0, maximum_brightness_duty=255,
        dsi_lanes=4, dsi_format="RGB888", dsi_flags_hex="0xa03",
        display_mode={"clock_hz": 35500000, "width": 720, "height": 720,
                      "hfront": 24, "hsync": 2, "hback": 30,
                      "vfront": 16, "vsync": 2, "vback": 8,
                      "pixelclk_active": 0, "de_active": 0, "hsync_active": 0, "vsync_active": 0},
        panel_delays_ms={"prepare": 50, "reset": 120, "init": 120, "enable": 220,
                         "disable": 120, "unprepare": 120},
        reset_gpio={"controller": "gpio0", "line": 5, "active_low": True},
        enable_gpio={"controller": "gpio0", "line": 21, "active_low": False},
        panel_regulator_uv=3300000, regulator_has_gpio=False,
        pwm={"provider": "pwm4", "channel": 0, "period_ns": 25000,
             "flags": 0, "bank": 0, "line": 19, "mux": 1},
        new_phandles=new_handles, loader_logo_mapping_enabled=False,
        board_tested=False, display_hardware_tested=False, deployable=False)
    return inherited


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(*uart.rng.wifi.base.read_dtb(args.dtb)), indent=2))
    except (ValueError, KeyError, OSError, struct.error) as error:
        parser.exit(1, "DISPLAY_AUDIT_REJECTED: " + str(error) + "\n")
