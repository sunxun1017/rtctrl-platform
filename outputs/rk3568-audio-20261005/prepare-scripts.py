#!/usr/bin/env python3
"""Adapt the previously fault-tested RAM staging and release boundaries."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "rk3568-cap1188-20261004"
REPLACE = {
    "rk3568-cap1188-20261004": "rk3568-audio-20261005",
    "rtctrl-cap1188-20261004": "rtctrl-audio-20261005",
    "tmp/cap1188": "tmp/audio",
    "tmp/cap-cache": "tmp/audio-cache",
    "cap1188-spi.dtb": "audio.dtb",
    "cap1188-inspect": "alsa-inspect",
    "linux-enumeration.sh linux-identity.sh": "snd-soc-rk817.ko linux-interface.sh",
    '"linux-enumeration.sh", "linux-identity.sh"': '"snd-soc-rk817.ko", "linux-interface.sh"',
    "CAP_INPUTS_IN_RAM_CACHE_RELEASED": "AUDIO_INPUTS_IN_RAM_CACHE_RELEASED",
    "CAP_INPUTS_STAGED": "AUDIO_INPUTS_STAGED",
    "CAP_RAM_ONLY_RESET_READY": "AUDIO_RAM_ONLY_RESET_READY",
    "identity-verified": "interface-verified",
    "identity-rejected": "interface-rejected",
}


def adapt(text):
    for old, new in REPLACE.items():
        text = text.replace(old, new)
    return text


def main():
    for name in ["linux-stage.sh", "prepare-android.sh", "test-linux-stage.py", "test-return-guard.py", "check-runtime-commands.py"]:
        target = HERE / name
        with target.open("x") as output:
            output.write(adapt((OLD / name).read_text()))
    guard = adapt((OLD / "linux-return-guard.sh").read_text())
    guard = guard.replace('test -z "$modules"', '''count=0
module_refs=0
if test -n "$modules"; then
    while read -r name size refs depends state rest; do
        test "$name" = snd_soc_rk817
        case "$refs" in
            0|1) ;;
            *) exit 1 ;;
        esac
        module_refs=$refs
        test "$depends" = -
        test "$state" = Live
        count=$((count + 1))
    done <<EOF
$modules
EOF
    test "$count" = 1
fi''')
    guard = guard.replace("interface-verified|interface-rejected) ;;", '''interface-verified)
        test "$count:$module_refs" = 1:1
        ;;
    interface-rejected) ;;''')
    guard = guard.replace("/dev/spidev*|/dev/input/*|", "/dev/snd/*|/dev/spidev*|/dev/input/*|")
    with (HERE / "linux-return-guard.sh").open("x") as output:
        output.write(guard)
    test = HERE / "test-return-guard.py"
    text = test.read_text().replace('"open SPI", "open UART0"', '"open SPI", "open control", "open PCM", "open UART0"')
    text = text.replace('"open UART0": "/dev/ttyS0",', '"open control": "/dev/snd/controlC1", "open PCM": "/dev/snd/pcmC1D0p", "open UART0": "/dev/ttyS0",')
    text = text.replace('"verified", "rejected", "nonroot"', '"verified", "rejected", "codec retained", "codec busy", "codec duplicate", "codec dependency", "nonroot"')
    text = text.replace('if case == "unexpected module":', '''if case.startswith("codec "):
                modules = "snd_soc_rk817 520656 1 - Live 0\\n"
                if case == "codec busy":
                    modules = modules.replace(" 1 - ", " 2 - ")
                if case == "codec dependency":
                    modules = modules.replace(" - ", " other ")
                if case == "codec duplicate":
                    modules += modules
                write("proc/modules", modules)
            if case == "unexpected module":''')
    text = text.replace('case in ["verified", "rejected"]', 'case in ["verified", "rejected", "codec retained"]')
    text = text.replace('write("proc/modules", "")', 'write("proc/modules", "" if case == "rejected" else "snd_soc_rk817 520656 1 - Live 0\\n")')
    test.write_text(text)
    stage_test = HERE / "test-linux-stage.py"
    stage_test.write_text(stage_test.read_text().replace(
        'for original in replacements)', 'for original in sorted(replacements, key=len, reverse=True))'))
    check = HERE / "check-runtime-commands.py"
    check.write_text(check.read_text().replace('"printf", "sh"', '"printf", "sh", "insmod"'))
    print("AUDIO_RUNTIME_SCRIPTS_GENERATED_NO_HARDWARE_ACTION")


if __name__ == "__main__":
    main()
