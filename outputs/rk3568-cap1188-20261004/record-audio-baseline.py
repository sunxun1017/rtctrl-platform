#!/usr/bin/env python3
"""Record valid read-only Android audio metadata; never play or capture audio."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def load(name):
    path = HERE / "private" / name
    return json.loads(path.read_text()), hashlib.sha256(path.read_bytes()).hexdigest()


def expect(records, key, pattern):
    item = records[key]
    if item["exit_code"] != 0 or not re.search(pattern, item["output"], re.M):
        raise ValueError("Audio baseline evidence missing: " + key)


def main():
    first, first_sha = load("android-audio-baseline-v2.json")
    details, details_sha = load("android-audio-details-v3.json")
    for key, pattern in {
        "kernel": r"^4\.19\.232$", "cards": r"rockchip,rk809-codec",
        "pcm": r"01-00: fe410000\.i2s-rk817-hifi .*playback 1 : capture 1",
        "audio_tools": r"^/system/bin/tinymix$", "codec_binding": r"^/sys/bus/platform/drivers/rk817-codec$",
        "card0_id": r"^Dongle$",
    }.items():
        expect(first, key, pattern)
    expect(first, "pcm", r"^00-00: USB Audio : USB Audio : capture 1$")
    for key, pattern in {
        "card1_id": r"^rockchiprk809co$", "card1_machine": r"^/sys/devices/platform/rk809-sound$",
        "card1_controls": r"^Number of controls: 2$", "amp_pin": r"pin 148 .*\(MUX UNCLAIMED\) gpio4:148",
        "sound_status": r"o\s+k\s+a\s+y", "cpu_dai": r"00 00 00 e1", "codec_dai": r"00 00 01 41",
        "codec_dt": r"^spk-ctl-gpios$", "battery": r"^  level: (\d+)$",
    }.items():
        expect(details, key, pattern)
    expect(details, "card1_controls", r"Playback Path\s+HP_NO_MIC$")
    expect(details, "card1_controls", r"Capture MIC Path\s+MIC OFF$")
    battery = int(re.search(r"^  level: (\d+)$", details["battery"]["output"], re.M).group(1))
    result = {
        "status": "ANDROID_AUDIO_METADATA_BASELINE_VERIFIED_NO_PLAYBACK_CAPTURE",
        "date": "2026-10-04", "kernel": "4.19.232", "battery_latest_percent": battery,
        "usb_audio": {"snapshot_card": 0, "id": "Dongle", "name": "Bothlent UAC Dongle", "capture_pcm_count": 1},
        "board_audio": {"snapshot_card": 1, "id": "rockchiprk809co", "name": "rockchip,rk809-codec",
                        "machine": "rk809-sound", "codec_driver": "rk817-codec", "cpu_dai": "fe410000.i2s",
                        "codec_dai": "rk817-hifi", "playback_pcm_count": 1, "capture_pcm_count": 1,
                        "control_count": 2, "controls_read": {"Playback Path": "HP_NO_MIC", "Capture MIC Path": "MIC OFF"},
                        "amp_gpio_mux_snapshot": "GPIO4_C4 pin148 GPIO owned; MUX unclaimed"},
        "boundaries": {"metadata_only": True, "card_number_stable_across_boots": False,
                       "playback_tested": False, "capture_tested": False, "path_control_changed": False,
                       "gpio_level_written": False, "new_linux_audio_driver_built": False,
                       "new_linux_audio_driver_loaded": False, "linux_board_audio_accepted": False,
                       "initial_unquoted_probe_used_as_evidence": False},
        "raw_evidence_sha256": {"android-audio-baseline-v2.json": first_sha, "android-audio-details-v3.json": details_sha},
        "next_analysis": "NEXT-AUDIO.md; locked 5.10 codec driver exists but CONFIG_SND_SOC_RK817 is disabled"
    }
    (HERE / "audio-baseline-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "battery_latest_percent": battery,
                      "board_controls": 2, "playback_or_capture": False}, indent=2))


if __name__ == "__main__":
    main()
