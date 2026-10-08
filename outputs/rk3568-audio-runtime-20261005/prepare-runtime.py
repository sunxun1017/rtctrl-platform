#!/usr/bin/env python3
"""Reuse tested RAM transfer and return guards for the PCM configuration stage."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "rk3568-audio-20261005"

def adapt(text):
    pairs = [
        ("rk3568-audio-20261005", "rk3568-audio-runtime-20261005"),
        ("rtctrl-audio-20261005", "rtctrl-pcm-20261005"),
        ("/tmp/audio", "/tmp/pcm"),
        ("tmp/audio", "tmp/pcm"),
        ("AUDIO_INPUTS", "PCM_INPUTS"),
        ("AUDIO_RAM_ONLY_RESET_READY", "PCM_RAM_ONLY_RESET_READY"),
        ("interface-verified", "pcm-verified"),
        ("interface-rejected", "pcm-rejected"),
        ("audio.dtb alsa-inspect", "audio.dtb alsa-inspect pcm-config"),
        ('"audio.dtb", "alsa-inspect",', '"audio.dtb", "alsa-inspect", "pcm-config",'),
        ("chmod 700 alsa-inspect", "chmod 700 alsa-inspect pcm-config"),
        ("alsa-inspect|wpa_supplicant", "alsa-inspect|pcm-config|wpa_supplicant"),
    ]
    for before, after in pairs:
        text = text.replace(before, after)
    return text

def main():
    for name in ["linux-stage.sh", "prepare-android.sh", "linux-return-guard.sh",
                 "test-linux-stage.py", "test-return-guard.py", "check-runtime-commands.py"]:
        with (HERE / name).open("x") as stream:
            stream.write(adapt((OLD / name).read_text()))
    print("PCM_RUNTIME_TRANSFER_AND_GUARD_SOURCES_PREPARED")

if __name__ == "__main__":
    main()
