#!/usr/bin/env python3
"""Bind the local board captures to a bounded public audio-interface result."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIVATE = HERE / "private"
EXPECTED = {
    "boot": "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28",
    "uboot": "4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e",
    "trust": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "dtbo": "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d",
    "vbmeta": "76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752",
    "source_rootfs": "4fcebae566d889072954b2f5b220474fe9accd75bbb48471023f24841b6ed95e",
    "network_rootfs": "32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def raw(name):
    return (PRIVATE / name).read_text().replace("\r", "")


def require(text, pattern):
    if not re.search(pattern, text, re.M):
        raise ValueError("Required board evidence missing: " + pattern)


def android(name):
    record = read(PRIVATE / name)
    sections = record["sections"]
    if any(item["exit_code"] != 0 for item in sections.values()):
        raise ValueError("Android evidence contains a failed command")
    for key, expected in {"kernel": "4.19.232", "android": "11", "boot_completed": "1"}.items():
        if sections[key]["output"].strip() != expected:
            raise ValueError("Android state mismatch: " + key)
    require(sections["root"]["output"], r"^uid=0\(root\)")
    for key, expected in EXPECTED.items():
        if sections[key + "_sha256"]["output"].split()[0] != expected:
            raise ValueError("Persistent fingerprint mismatch: " + key)
    require(sections["cards"]["output"], r"1 \[rockchiprk809co\]")
    require(sections["pcm"]["output"], r"^01-00:.*playback 1 : capture 1$")
    return record, int(re.search(r"^  level: (\d+)$", sections["battery"]["output"], re.M).group(1))


def main():
    before, battery_before = android("android-before-v2.json")
    after, battery_after = android("android-after.json")
    final = read(PRIVATE / "android-final-state.json")
    for key, item in final["sections"].items():
        if item["exit_code"] != 0:
            raise ValueError("Final Android command failed: " + key)
    for key, expected in {"kernel": "4.19.232", "android": "11", "boot_completed": "1"}.items():
        if final["sections"][key]["output"].strip() != expected:
            raise ValueError("Final Android state mismatch")
    require(final["sections"]["root"]["output"], r"^uid=0\(root\)")
    battery_final = int(re.search(r"^  level: (\d+)$", final["sections"]["battery"]["output"], re.M).group(1))
    names = ["load-ram.raw.txt", "boot-ram.raw.txt", "linux-stage.raw.txt",
             "linux-interface.raw.txt", "return-android.raw.txt", "android-boot-inputs.txt"]
    logs = {name: raw(name) for name in names}
    for crc in ["c91762d1", "c69f4dbf", "74fea1e6"]:
        require(logs["load-ram.raw.txt"], "==> " + crc)
    require(logs["boot-ram.raw.txt"], r"^Source Linux userspace test: PID1 remains in RAM$")
    require(logs["linux-stage.raw.txt"], r"^AUDIO_INPUTS_IN_RAM_CACHE_RELEASED$")
    stage_lines = re.findall(r"^(?:audio\.dtb|snd-soc-rk817\.ko|alsa-inspect|linux-interface\.sh|linux-return-guard\.sh): OK$",
                             logs["linux-stage.raw.txt"], re.M)
    if len(stage_lines) != 10:
        raise ValueError("Two full staged hash checks missing")
    interface = logs["linux-interface.raw.txt"]
    require(interface, r"^snd_soc_rk817 20480 1 - Live .+ \(O\)$")
    require(interface, r"^ALSA_CARD card=1 id=rockchiprk809co controls=14$")
    require(interface, r"^01-00:.*playback 1 : capture 1$")
    controls = [
        {"numid": 12, "name": "Playback Path", "items": 11, "value": 0, "label": "OFF"},
        {"numid": 13, "name": "Capture MIC Path", "items": 4, "value": 0, "label": "MIC OFF"},
        {"numid": 14, "name": "Resume Path", "items": 2, "value": 0, "label": "OFF"},
    ]
    for control in controls:
        line = "ALSA_CONTROL numid={numid} name={name} items={items} value={value} label={label}".format(**control)
        require(interface, "^" + re.escape(line) + "$")
    require(interface, r"^ALSA_CODEC_INTERFACE_VERIFIED$")
    require(interface, r"^AUDIO_METADATA_COMPLETE_NO_PCM_OPEN_NO_CONTROL_WRITE$")
    pin_groups = {34: "mclk", 35: "sclktx", 37: "lrcktx", 39: "sdo0", 43: "sdi0"}
    for pin, group in pin_groups.items():
        require(interface, rf"^pin {pin} .*function i2s1 group i2s1m0-{group}$")
    require(interface, r"^\s+mclk_i2s1_8ch_tx\s+1\s+1\s+0\s+12288000\s+")
    require(interface, r"^ gpio-148 .*\|spk-ctl\s*\) out hi ACTIVE LOW$")
    require(interface, r"^0: uart:16550A mmio:0xFDD50000 irq:\d+ tx:0 rx:0$")
    returned = logs["return-android.raw.txt"]
    require(returned, r"^AUDIO_RAM_ONLY_RESET_READY$")
    reset = re.search(r"^\[\s*([0-9.]+)\] sysrq: Resetting\nDDR ", returned, re.M)
    if not reset:
        raise ValueError("SysRq/DDR return boundary missing")
    source_segment = returned[:reset.start()]
    if re.search(r"WARNING:|BUG:|Call trace:", source_segment):
        raise ValueError("Source Linux warning/oops in captured return log")
    mounts = re.findall(r"^(\S+) (\S+) (\S+) (\S+) 0 0$", returned[:returned.index("AUDIO_RAM_ONLY_RESET_READY")], re.M)
    if len(mounts) != 5 or {item[2] for item in mounts} != {"rootfs", "devtmpfs", "proc", "sysfs", "tmpfs"}:
        raise ValueError("Final mount evidence is not five RAM/pseudo filesystems")
    runtime = read(HERE / "runtime-manifest.json")
    paths = {"audio.dtb": HERE / "build/dtb-v3/audio.dtb",
             "snd-soc-rk817.ko": HERE / "driver-modules-v4/modules/snd-soc-rk817.ko",
             "alsa-inspect": HERE / "build/inspect-v4/alsa-inspect"}
    for name, expected in runtime["files"].items():
        if sha(paths.get(name, HERE / name)) != expected:
            raise ValueError("Tested runtime input changed: " + name)
    image_sha = "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457"
    initrd_sha = "f0965ceed549acab8d5bd87df8bb831bb06a95d08b5b7bf3c5582045933323ee"
    for digest in [image_sha, initrd_sha]:
        require(logs["android-boot-inputs.txt"], "^" + digest + "  /")
    host_path = HERE / "build/host-checks-v1/result.json"
    host = read(host_path)
    if host["status"] != "AUDIO_CURRENT_HOST_INPUTS_VERIFIED":
        raise ValueError("Current host verification missing")
    for script, digest in host["runtime_checks"]["check-runtime-commands.py"]["script_sha256"].items():
        if sha(HERE / script) != digest:
            raise ValueError("Runtime host check stale")
    record = {
        "status": "RK809_ALSA_INTERFACE_VERIFIED_IN_RAM_RETURNED_TO_ANDROID",
        "date": "2026-10-05", "kernel_release": "5.10.160-rt89-g9f9e9d18574d-dirty",
        "kernel_commit": "9f9e9d18574d0914c0d192a90c3babfe1fd63c95",
        "image_sha256": image_sha, "initramfs_sha256": initrd_sha,
        "tested_runtime_sha256": runtime["files"],
        "codec_patch_sha256": "f501e5642d363b0c10431de053c19d8c1ae16060ddb35838d520de0f0d84bd81",
        "dtb": {"bytes": 163161, "crc32": "c69f4dbf", "checks": 177, "faults_rejected": 23,
                "property_changes": 29, "old_phandles_retained": 760, "new_dtc_warnings": 0},
        "codec": {"module_bytes": 515240, "module_imports_from_exact_image": 32,
                  "real_function_host_cases": 73, "real_function_qemu_cases": 73,
                  "regmap_ownership": "borrow original PMIC map; never allocate/free",
                  "chip_name_log": "0x80", "chip_version_log": "0x95",
                  "fresh_bus_identity_proven": False, "module_refcount_before_reset": 1},
        "alsa": {"card_number_this_boot": 1, "card_id": "rockchiprk809co", "controls_listed": 14,
                 "controls_inspected": controls, "playback_endpoint": "pcmC1D0p",
                 "capture_endpoint": "pcmC1D0c", "interface_verified": True,
                 "helper_host_cases": 114, "helper_qemu_cases": 114,
                 "helper_default_alarm_seconds": 5, "pcm_opened": False, "controls_written": False,
                 "unknown_controls_list_only": True, "cached_OFF_is_not_electrical_acceptance": True},
        "runtime": {"pin_groups": pin_groups, "mclk_kernel_rate_hz": 12288000,
                    "gpio148_kernel_state": "out hi ACTIVE LOW; consumer spk-ctl",
                    "physical_voltage_measured": False, "uart0_tx_rx": [0, 0],
                    "stage_fixtures": 18, "reset_guard_fixtures": 31,
                    "only_five_ram_pseudo_mounts_at_reset": True,
                    "loop_network_audio_fd_residuals_rejected_by_guard": True,
                    "module_retained_until_reset": True, "module_unload_tested": False,
                    "sysrq_reset_seconds": float(reset.group(1)),
                    "WARNING_BUG_Call_trace_in_source_return_capture": False,
                    "codec_DMA_mask_notice_seen": True,
                    "DMA_mask_notice_source": "OF platform configuration supplies missing pointer; codec uses no DMA API",
                    "PCM_DMA_verified": False},
        "returned_android": {"kernel": "4.19.232", "release": 11, "root": True,
                             "boot_completed": True, "battery_before_percent": battery_before,
                             "battery_after_percent": battery_after, "after_timestamp": after["timestamp"],
                             "battery_final_percent": battery_final, "final_timestamp": final["timestamp"]},
        "persistent_integrity": {"seven_before_after_full_SHA_equal": True, "sha256": EXPECTED,
                                 "full_emmc_diff": False, "bare_metal_restore_tested": False},
        "boundaries": {"headphones_or_speakers_connected": False, "motor_connected": False,
                       "motor_or_MCU_commands": False, "saveenv": False, "startup_partition_write": False,
                       "switch_root": False, "normal_poweroff_verified": False,
                       "factory_custom_so_required_for_this_interface_test": False,
                       "all_factory_audio_behavior_replaced": False},
        "evidence_sha256": {name: sha(PRIVATE / name) for name in names + [
            "android-before-v2.json", "android-after.json", "android-final-state.json", "android-helper.json"]},
        "host_result_sha256": sha(host_path), "recorder_sha256": sha(Path(__file__)),
        "limitations": ["No PCM stream, sound quality, channel mapping or amp electrical acceptance",
                        "Runtime path/mute/hw_params/suspend/resume errors and full removal concurrency remain unaudited/unfixed",
                        "Probe writes GPIO/clock/reset/configuration despite metadata-only userspace",
                        "Early proc cards read raced registration; later helper/sysfs/PCM identify card 1",
                        "Android helper rejected cached path metadata with generic rc2; failing branch not proven",
                        "Build manifests are immutable pre-board records; board acceptance is in this result",
                        "Other peripheral identity gaps and motor feedback/stop/enable/watchdog remain"]}
    (HERE / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print("RK809_ALSA_INTERFACE_VERIFIED: 14 controls; seven persistent SHA equal; Android battery " + str(battery_final) + "%")


if __name__ == "__main__":
    main()
