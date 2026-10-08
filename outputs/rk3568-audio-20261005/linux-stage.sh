#!/bin/sh
# Copy verified diagnostic inputs into RAM, then release read-only cache.
set -eu
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f62696e2f7368002f696e697400
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
modules=$(cat /proc/modules)
test -z "$modules"
test ! -e /dev/McuCom
test ! -e /tmp/audio
mounts=$(cat /proc/mounts)
while read -r source target kind rest; do
    case "$kind" in
        rootfs|devtmpfs|proc|sysfs|tmpfs) ;;
        *) exit 1 ;;
    esac
done <<EOF
$mounts
EOF
mkdir /tmp/audio /tmp/audio-cache
mounted=0
release_cache() {
    if test "$mounted" = 1; then
        cd / || return 1
        umount /tmp/audio-cache || return 1
        mounted=0
    fi
}
trap release_cache EXIT
trap 'exit 1' HUP INT TERM
mount -t ext4 -o ro,noload /dev/mmcblk0p12 /tmp/audio-cache
mounted=1
cd /tmp/audio-cache/rtctrl-audio-20261005
sha256sum -c upload.sha256
cp audio.dtb alsa-inspect snd-soc-rk817.ko linux-interface.sh linux-return-guard.sh upload.sha256 /tmp/audio/
cd /tmp/audio
sha256sum -c upload.sha256
chmod 700 alsa-inspect
cd /
release_cache
trap - EXIT HUP INT TERM
echo AUDIO_INPUTS_IN_RAM_CACHE_RELEASED
