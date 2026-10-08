#!/bin/sh
# Load the checked codec; inspect metadata without PCM or control writes.
set -eu
test ! -e /tmp/audio/outcome
echo interface-rejected > /tmp/audio/outcome
cd /tmp/audio
sha256sum -c upload.sha256
modules=$(cat /proc/modules)
test -z "$modules"
insmod /tmp/audio/snd-soc-rk817.ko
test "$(readlink -f /sys/bus/platform/devices/rk817-codec/driver)" = /sys/bus/platform/drivers/rk817-codec
cat /proc/modules
cat /proc/asound/cards
cat /proc/asound/pcm
ls -l /dev/snd

found=0
card=
for file in /proc/asound/card[0-7]/id; do
    test -f "$file" || continue
    identity=$(cat "$file")
    if test "$identity" = rockchiprk809co; then
        found=$((found + 1))
        card=${file#/proc/asound/card}
        card=${card%/id}
    fi
done
test "$found" = 1
test "$(readlink -f /sys/class/sound/card$card/device)" = /sys/devices/platform/rk809-sound
grep "fe410000.i2s-rk817-hifi" /proc/asound/pcm | grep "playback 1 : capture 1"
/tmp/audio/alsa-inspect --inspect --card "$card" > /tmp/audio/controls.txt
cat /tmp/audio/controls.txt
grep '^ALSA_CODEC_INTERFACE_VERIFIED$' /tmp/audio/controls.txt

mkdir /tmp/audio-debug
mounted=0
release_debug() {
    if test "$mounted" = 1; then
        cd / || return 1
        umount /tmp/audio-debug || return 1
        mounted=0
    fi
}
trap release_debug EXIT
trap 'exit 1' HUP INT TERM
mount -t debugfs -o ro debugfs /tmp/audio-debug
mounted=1
grep -E 'pin (34|35|37|39|43|148) ' /tmp/audio-debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins
grep -E 'i2s1|rk817' /tmp/audio-debug/clk/clk_summary
grep -E 'gpio-148|spk-ctl' /tmp/audio-debug/gpio
cat /proc/tty/driver/serial
cd /
release_debug
trap - EXIT HUP INT TERM
echo interface-verified > /tmp/audio/outcome
echo AUDIO_METADATA_COMPLETE_NO_PCM_OPEN_NO_CONTROL_WRITE
