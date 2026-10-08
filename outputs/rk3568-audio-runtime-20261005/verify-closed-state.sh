#!/bin/sh
# Read-only continuation after rejected v2 comparison; never repeats PCM setup.
set -eu
test "$(cat /tmp/pcm/outcome)" = pcm-rejected
test ! -e /tmp/pcm/closed-state-outcome
echo closed-state-rejected > /tmp/pcm/closed-state-outcome
cd /tmp/pcm
sha256sum -c upload.sha256
grep '^PCM_CONFIGURATION_VERIFIED_NO_START$' playback.txt
grep '^PCM_CONFIGURATION_VERIFIED_NO_START$' capture.txt
grep '^PCM_STATE configured=SETUP appl_ptr=0 hw_ptr=0$' playback.txt
grep '^PCM_STATE configured=SETUP appl_ptr=0 hw_ptr=0$' capture.txt
grep '^PCM_STATE freed=OPEN$' playback.txt
grep '^PCM_STATE freed=OPEN$' capture.txt
test "$(cat controls-before.txt)" = "$(cat controls-after.txt)"
/tmp/pcm/alsa-inspect --inspect --card 1 > controls-closed.txt
test "$(cat controls-after.txt)" = "$(cat controls-closed.txt)"
cat controls-closed.txt
test "$(cat /proc/asound/card1/id)" = rockchiprk809co
test "$(readlink -f /sys/class/sound/card1/device)" = /sys/devices/platform/rk809-sound
for direction in p c; do
    test "$(cat /proc/asound/card1/pcm0"$direction"/sub0/status)" = closed
    test "$(cat /proc/asound/card1/pcm0"$direction"/sub0/hw_params)" = closed
done
test "$(cat /sys/bus/platform/devices/fe410000.i2s/power/runtime_status)" = suspended
mkdir /tmp/pcm-closed-debug
mounted=0
release_debug() {
    if test "$mounted" = 1; then
        cd / || return 1
        umount /tmp/pcm-closed-debug || return 1
        mounted=0
    fi
}
trap release_debug EXIT
trap 'exit 1' HUP INT TERM
mount -t debugfs -o ro debugfs /tmp/pcm-closed-debug
mounted=1
grep -E 'i2s1|rk817' /tmp/pcm-closed-debug/clk/clk_summary > clocks-closed.txt
test "$(cat clocks-after.txt)" = "$(cat clocks-closed.txt)"
sh /tmp/pcm-clock-profile.sh clocks-before.txt clocks-closed.txt
cat clocks-closed.txt
grep -E 'gpio-148|spk-ctl' /tmp/pcm-closed-debug/gpio > gpio-closed.txt
test "$(cat gpio-before.txt)" = "$(cat gpio-closed.txt)"
cat gpio-closed.txt
test -f /tmp/pcm-closed-debug/dmaengine/summary
cat /tmp/pcm-closed-debug/dmaengine/summary > dma-closed.txt
test "$(cat dma-before.txt)" = "$(cat dma-closed.txt)"
cat dma-closed.txt
cd /
release_debug
trap - EXIT HUP INT TERM
# This guard scans all FD links and refuses running PCM tools/resources.
sh /tmp/pcm/linux-return-guard.sh
echo closed-state-verified > /tmp/pcm/closed-state-outcome
echo PCM_CONFIGURATION_AND_CLOSED_STATE_VERIFIED_NO_START
