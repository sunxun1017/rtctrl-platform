#!/bin/sh
# Configure both PCM directions without preparing, starting, or reading/writing frames.
set -eu
test ! -e /tmp/pcm/outcome
echo pcm-rejected > /tmp/pcm/outcome
cd /tmp/pcm
sha256sum -c upload.sha256
modules=$(cat /proc/modules)
test -z "$modules"
insmod /tmp/pcm/snd-soc-rk817.ko
test "$(readlink -f /sys/bus/platform/devices/rk817-codec/driver)" = /sys/bus/platform/drivers/rk817-codec

found=0
card=
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
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
    if test "$found" = 1 && test -e /dev/snd/controlC"$card" &&
        test -e /dev/snd/pcmC"$card"D0p && test -e /dev/snd/pcmC"$card"D0c; then
        break
    fi
    test "$found" -le 1
    sleep 1
done
test "$found" = 1
test -e /dev/snd/controlC"$card"
test -e /dev/snd/pcmC"$card"D0p
test -e /dev/snd/pcmC"$card"D0c
test "$(readlink -f /sys/class/sound/card$card/device)" = /sys/devices/platform/rk809-sound
cat /proc/modules
cat /proc/asound/cards
cat /proc/asound/pcm
ls -l /dev/snd
/tmp/pcm/alsa-inspect --inspect --card "$card" > /tmp/pcm/controls-before.txt
cat /tmp/pcm/controls-before.txt

mkdir /tmp/pcm-debug
mounted=0
release_debug() {
    if test "$mounted" = 1; then
        cd / || return 1
        umount /tmp/pcm-debug || return 1
        mounted=0
    fi
}
trap release_debug EXIT
trap 'exit 1' HUP INT TERM
mount -t debugfs -o ro debugfs /tmp/pcm-debug
mounted=1
grep -E 'i2s1|rk817' /tmp/pcm-debug/clk/clk_summary > /tmp/pcm/clocks-before.txt
cat /tmp/pcm/clocks-before.txt
grep -E 'gpio-148|spk-ctl' /tmp/pcm-debug/gpio > /tmp/pcm/gpio-before.txt
cat /tmp/pcm/gpio-before.txt
if test -f /tmp/pcm-debug/dmaengine/summary; then
    cat /tmp/pcm-debug/dmaengine/summary > /tmp/pcm/dma-before.txt
    cat /tmp/pcm/dma-before.txt
fi
runtime_before=$(cat /sys/bus/platform/devices/fe410000.i2s/power/runtime_status)
printf '%s\n' "$runtime_before"
test "$(cat /proc/asound/card"$card"/pcm0p/sub0/status)" = closed
test "$(cat /proc/asound/card"$card"/pcm0c/sub0/status)" = closed

/tmp/pcm/pcm-config --configure --card "$card" --stream playback > /tmp/pcm/playback.txt
cat /tmp/pcm/playback.txt
grep '^PCM_CONFIGURATION_VERIFIED_NO_START$' /tmp/pcm/playback.txt
/tmp/pcm/pcm-config --configure --card "$card" --stream capture > /tmp/pcm/capture.txt
cat /tmp/pcm/capture.txt
grep '^PCM_CONFIGURATION_VERIFIED_NO_START$' /tmp/pcm/capture.txt

/tmp/pcm/alsa-inspect --inspect --card "$card" > /tmp/pcm/controls-after.txt
test "$(cat /tmp/pcm/controls-before.txt)" = "$(cat /tmp/pcm/controls-after.txt)"
cat /tmp/pcm/controls-after.txt
test "$(cat /proc/asound/card"$card"/pcm0p/sub0/status)" = closed
test "$(cat /proc/asound/card"$card"/pcm0c/sub0/status)" = closed
test "$(cat /proc/asound/card"$card"/pcm0p/sub0/hw_params)" = closed
test "$(cat /proc/asound/card"$card"/pcm0c/sub0/hw_params)" = closed
runtime_after=$(cat /sys/bus/platform/devices/fe410000.i2s/power/runtime_status)
test "$runtime_before" = "$runtime_after"
printf '%s\n' "$runtime_after"
grep -E 'i2s1|rk817' /tmp/pcm-debug/clk/clk_summary > /tmp/pcm/clocks-after.txt
test "$(cat /tmp/pcm/clocks-before.txt)" = "$(cat /tmp/pcm/clocks-after.txt)"
cat /tmp/pcm/clocks-after.txt
grep -E 'gpio-148|spk-ctl' /tmp/pcm-debug/gpio > /tmp/pcm/gpio-after.txt
test "$(cat /tmp/pcm/gpio-before.txt)" = "$(cat /tmp/pcm/gpio-after.txt)"
cat /tmp/pcm/gpio-after.txt
if test -f /tmp/pcm-debug/dmaengine/summary; then
    cat /tmp/pcm-debug/dmaengine/summary > /tmp/pcm/dma-after.txt
    test "$(cat /tmp/pcm/dma-before.txt)" = "$(cat /tmp/pcm/dma-after.txt)"
    cat /tmp/pcm/dma-after.txt
fi
cat /proc/tty/driver/serial
cat /proc/modules
echo PCM_FDS_CLOSED_HW_PARAMS_CLOSED_RUNTIME_CLOCK_GPIO_BINDINGS_RESTORED
cd /
release_debug
trap - EXIT HUP INT TERM
echo pcm-verified > /tmp/pcm/outcome
echo PCM_CONFIGURATION_COMPLETE_NO_PREPARE_NO_START_NO_AUDIO_FRAMES
