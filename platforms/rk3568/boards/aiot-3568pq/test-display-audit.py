#!/usr/bin/env python3
"""Compile real display DTB faults and require the public auditor to reject each."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    parser.add_argument("preprocessed", type=Path)
    parser.add_argument("--audit-script", type=Path, default=BOARD / "verify-display.py")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    assert args.audit_script.is_file(), "Display audit feature is not implemented"
    spec = importlib.util.spec_from_file_location("display_audit", args.audit_script)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    panel = "&{/dsi@fe060000/panel@0}"
    timing = "&{/dsi@fe060000/panel@0/display-timings/timing0}"
    regulator = "&{/vcc3v3-lcd0-n}"
    backlight = "&{/backlight}"
    cases = {
        "display subsystem disabled": '&display_subsystem { status = "disabled"; };',
        "VOP disabled": '&vop { status = "disabled"; };',
        "VOP MMU disabled": '&vop_mmu { status = "disabled"; };',
        "DSI disabled": '&dsi0 { status = "disabled"; };',
        "DSI PHY disabled": '&video_phy0 { status = "disabled"; };',
        "PWM4 disabled": '&pwm4 { status = "disabled"; };',
        "VP0 input enabled": '&dsi0_in_vp0 { status = "okay"; };',
        "VP1 input disabled": '&dsi0_in_vp1 { status = "disabled"; };',
        "wrong VOP input remote": '&dsi0_in_vp1 { remote-endpoint = <&vp0_out_dsi0>; };',
        "wrong VOP output remote": '&vp1_out_dsi0 { remote-endpoint = <&dsi0_in_vp0>; };',
        "wrong host output remote": '&dsi0_out { remote-endpoint = <&vp1_out_dsi0>; };',
        "wrong panel remote": '&panel_in_dsi { remote-endpoint = <&vp1_out_dsi0>; };',
        "missing panel remote": '&panel_in_dsi { /delete-property/ remote-endpoint; };',
        "wrong DSI host PHY": '&dsi0 { phys = <&video_phy1>; };',
        "guessed DSI hs clock": '&dsi0 { clocks = <&cru 232 &cru 218 &video_phy0>; clock-names = "pclk", "hclk", "hs_clk"; };',
        "wrong DSI compatible": '&dsi0 { compatible = "rockchip,rk3399-mipi-dsi"; };',
        "wrong DSI register": '&dsi0 { reg = <0 0xfe070000 0 0x10000>; };',
        "wrong PHY clock": '&video_phy0 { clocks = <&pmucru 24 &cru 378 &cru 232>; };',
        "wrong panel identity": panel + ' { compatible = "other-panel"; };',
        "panel disabled": panel + ' { status = "disabled"; };',
        "wrong panel address": panel + ' { reg = <1>; };',
        "wrong DSI format": panel + ' { dsi,format = <3>; };',
        "wrong DSI lane count": panel + ' { dsi,lanes = <2>; };',
        "missing burst flag": panel + ' { dsi,flags = <0xa01>; };',
        "missing EOT bit9": panel + ' { dsi,flags = <0x803>; };',
        "invented noncontinuous bit10": panel + ' { dsi,flags = <0xe03>; };',
        "missing LPM flag": panel + ' { dsi,flags = <0x203>; };',
        "wrong screen type": panel + ' { screen-type = <3>; };',
        "wrong panel supply": panel + ' { power-supply = <&vcc3v3_sys>; };',
        "wrong panel backlight": panel + ' { backlight = <&vcc3v3_lcd0_n>; };',
        "wrong reset polarity": panel + ' { reset-gpios = <&gpio0 5 0>; };',
        "wrong reset pin": panel + ' { reset-gpios = <&gpio0 6 1>; };',
        "wrong reset controller": panel + ' { reset-gpios = <&gpio1 5 1>; };',
        "wrong enable polarity": panel + ' { enable-gpios = <&gpio0 21 1>; };',
        "wrong enable pin": panel + ' { enable-gpios = <&gpio0 20 0>; };',
        "wrong enable controller": panel + ' { enable-gpios = <&gpio1 21 0>; };',
        "missing panel reset": panel + ' { /delete-property/ reset-gpios; };',
        "missing panel enable": panel + ' { /delete-property/ enable-gpios; };',
        "wrong prepare delay": panel + ' { prepare-delay-ms = <0>; };',
        "wrong reset delay": panel + ' { reset-delay-ms = <20>; };',
        "wrong init delay": panel + ' { init-delay-ms = <0>; };',
        "wrong enable delay": panel + ' { enable-delay-ms = <0>; };',
        "wrong disable delay": panel + ' { disable-delay-ms = <0>; };',
        "wrong unprepare delay": panel + ' { unprepare-delay-ms = <0>; };',
        "truncated init command": panel + ' { panel-init-sequence = [13 02 02 ff]; };',
        "zero length init command": panel + ' { panel-init-sequence = [13 02 00]; };',
        "wrong init payload": panel + ' { panel-init-sequence = [13 02 02 ff 31 05 78 01 11 05 78 01 29]; };',
        "missing init sequence": panel + ' { /delete-property/ panel-init-sequence; };',
        "wrong exit order": panel + ' { panel-exit-sequence = [05 00 01 10 05 00 01 28]; };',
        "exit truncated": panel + ' { panel-exit-sequence = [05 00 01 28 05 00 01]; };',
        "missing exit sequence": panel + ' { /delete-property/ panel-exit-sequence; };',
        "wrong native timing": '&{/dsi@fe060000/panel@0/display-timings} { native-mode = <&panel_in_dsi>; };',
        "wrong pixel clock": timing + ' { clock-frequency = <36000000>; };',
        "wrong horizontal active": timing + ' { hactive = <800>; };',
        "wrong vertical active": timing + ' { vactive = <800>; };',
        "wrong horizontal front porch": timing + ' { hfront-porch = <32>; };',
        "wrong horizontal sync": timing + ' { hsync-len = <8>; };',
        "wrong horizontal back porch": timing + ' { hback-porch = <8>; };',
        "wrong vertical front porch": timing + ' { vfront-porch = <8>; };',
        "wrong vertical sync": timing + ' { vsync-len = <4>; };',
        "wrong vertical back porch": timing + ' { vback-porch = <4>; };',
        "wrong pixel clock polarity": timing + ' { pixelclk-active = <1>; };',
        "wrong data enable polarity": timing + ' { de-active = <1>; };',
        "wrong horizontal sync polarity": timing + ' { hsync-active = <1>; };',
        "wrong vertical sync polarity": timing + ' { vsync-active = <1>; };',
        "wrong regulator identity": regulator + ' { compatible = "regulator-gpio"; };',
        "wrong regulator lower voltage": regulator + ' { regulator-min-microvolt = <1800000>; };',
        "wrong regulator upper voltage": regulator + ' { regulator-max-microvolt = <5000000>; };',
        "wrong regulator input": regulator + ' { vin-supply = <&vcc5v0_sys>; };',
        "invented regulator GPIO": regulator + ' { gpio = <&gpio0 21 0>; };',
        "regulator disabled": regulator + ' { status = "disabled"; };',
        "missing regulator boot-on": regulator + ' { /delete-property/ regulator-boot-on; };',
        "wrong regulator suspend state": '&{/vcc3v3-lcd0-n/regulator-state-mem} { /delete-property/ regulator-off-in-suspend; regulator-on-in-suspend; };',
        "wrong backlight identity": backlight + ' { compatible = "gpio-backlight"; };',
        "wrong PWM provider": backlight + ' { pwms = <&pwm0 0 25000 0>; };',
        "wrong PWM channel": backlight + ' { pwms = <&pwm4 1 25000 0>; };',
        "wrong PWM period": backlight + ' { pwms = <&pwm4 0 50000 0>; };',
        "wrong PWM polarity": backlight + ' { pwms = <&pwm4 0 25000 1>; };',
        "unsafe full default backlight": backlight + ' { default-brightness-level = <255>; };',
        "original high default backlight": backlight + ' { default-brightness-level = <128>; };',
        "nonzero initial backlight before panel verification": backlight + ' { default-brightness-level = <32>; };',
        "wrong brightness table": backlight + ' { brightness-levels = <0 255>; };',
        "invented backlight GPIO": backlight + ' { enable-gpios = <&gpio0 21 0>; };',
        "wrong PWM4 pin": '&pwm4_pins { rockchip,pins = <0 20 1 &pcfg_pull_none>; };',
        "wrong PWM4 mux": '&pwm4_pins { rockchip,pins = <0 19 0 &pcfg_pull_none>; };',
        "wrong PWM4 pull": '&pwm4_pins { rockchip,pins = <0 19 1 &pcfg_pull_up>; };',
        "loader logo mapping restored": '&display_subsystem { memory-region = <&drm_logo &drm_cubic_lut>; };',
        "loader memory region names restored": '&display_subsystem { memory-region-names = "drm-logo", "drm-cubic-lut"; };',
        "loader DSI0 route enabled": '&route_dsi0 { status = "okay"; };',
        "loader DSI1 route enabled": '&route_dsi1 { status = "okay"; };',
        "loader HDMI route enabled": '&route_hdmi { status = "okay"; };',
        "loader eDP route enabled": '&route_edp { status = "okay"; };',
        "loader LVDS route enabled": '&route_lvds { status = "okay"; };',
        "loader RGB route enabled": '&route_rgb { status = "okay"; };',
        "reserved logo size changed": '&drm_logo { reg = <0 0xedf00000 0 0x300000>; };',
        "high remap reservation removed": '&{/reserved-memory/buffer@1f0000000} { /delete-property/ no-map; };',
        "original phandle changed": '&uart0 { phandle = <0x10000>; };',
        "unrelated UART disabled": '&uart0 { status = "disabled"; };',
        "unrelated sensor enabled": '&i2c5 { status = "okay"; };',
        "unrelated SPI enabled": '&spi3 { status = "okay"; };',
        "unrelated audio enabled": '&i2s1_8ch { status = "okay"; };',
        "unrelated extra property": '/ { display-audit-escape = <1>; };',
    }
    tree, reservations = audit.uart.rng.wifi.base.read_dtb(args.dtb)
    result = audit.audit(tree, reservations)
    assert result["board_tested"] is False
    assert result["default_brightness_index"] == 0
    assert result["init_sequence_bytes"] == 898
    assert result["init_sequence_commands"] == 180
    assert result["init_sequence_delay_ms"] == 596
    init = tree["/dsi@fe060000/panel@0/panel-init-sequence"]
    payload_fault = bytearray(init)
    payload_fault[4] ^= 1
    cases["same size init payload changed"] = panel + ' { panel-init-sequence = [' + payload_fault.hex(" ") + ']; };'
    delay_fault = bytearray(init)
    delay_fault[1] = 1
    delay_fault[6] = 3
    cases["same size same total init delay changed"] = panel + ' { panel-init-sequence = [' + delay_fault.hex(" ") + ']; };'
    type_fault = bytearray(init)
    type_fault[0] = 0x23
    cases["same size init packet type changed"] = panel + ' { panel-init-sequence = [' + type_fault.hex(" ") + ']; };'
    levels = tree["/backlight/brightness-levels"]
    level_values = [int.from_bytes(levels[index:index + 4], "big") for index in range(0, len(levels), 4)]
    level_values[200] -= 1
    cases["same size nondefault brightness entry changed"] = backlight + ' { brightness-levels = <' + ' '.join(map(str, level_values)) + '>; };'
    dtc = ROOT / ".deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc"
    work = args.output or (args.dtb.parent / "faults")
    if work.exists() or work.is_symlink() or work.parent.is_symlink():
        raise ValueError("Refusing existing or symlink fault output")
    work.mkdir(parents=True)
    passed = []
    source_bytes = args.preprocessed.read_bytes()
    mutations = [(name, source_bytes + overlay.encode() + b"\n") for name, overlay in cases.items()]
    mutations.append(("FDT memreserve added", source_bytes.replace(
        b"/dts-v1/;", b"/dts-v1/;\n/memreserve/ 0x10000000 0x1000;", 1)))
    for index, (name, data) in enumerate(mutations):
        source = work / (str(index) + ".dts")
        source.write_bytes(data)
        candidate = work / (str(index) + ".dtb")
        compiled = subprocess.run([
            str(dtc), "-@", "-I", "dts", "-O", "dtb", "-o", str(candidate), str(source)],
            capture_output=True, check=True)
        (work / (str(index) + ".dtc.log")).write_bytes(compiled.stderr)
        rejected = subprocess.run([
            "python3", str(args.audit_script), str(candidate)], capture_output=True, text=True)
        assert rejected.returncode == 1 and "DISPLAY_AUDIT_REJECTED:" in rejected.stderr, (
            "Invalid compiled DTB accepted or audit crashed: " + name + "\n" + rejected.stderr)
        passed.append({"name": name, "dtb_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                       "rejection": rejected.stderr.strip()})
    print(json.dumps({"status": "DISPLAY_REAL_DTB_FAULTS_PASSED", "faults_rejected": len(passed),
                      "fault_artifacts": str(work.relative_to(ROOT)), "passed": passed}, indent=2))


if __name__ == "__main__":
    main()
