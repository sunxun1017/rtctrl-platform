#!/bin/sh
# Refuse reset until all diagnostic descriptors and persistent mounts are gone.
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
loops=$(losetup -a)
test -z "$loops"
mounts=$(cat /proc/mounts)
while read -r source target kind rest; do
    case "$kind" in
        rootfs|devtmpfs|proc|sysfs|tmpfs) ;;
        *) exit 1 ;;
    esac
done <<EOF
$mounts
EOF
test ! -e /sys/class/net/wlan0
test ! -e /dev/McuCom
test ! -e /tmp/cap-cache/rtctrl-cap1188-20261004
outcome=$(cat /tmp/cap1188/outcome)
case "$outcome" in
    identity-verified|identity-rejected) ;;
    *) exit 1 ;;
esac
for process in /proc/[0-9]*; do
    test -d "$process" || continue
    comm=$(cat "$process/comm") || exit 1
    case "$comm" in
        cap1188-inspect|wpa_supplicant|udhcpc|tcp-probe) exit 1 ;;
    esac
    for fd in "$process"/fd/*; do
        test -L "$fd" || continue
        target=$(readlink "$fd") || exit 1
        case "$target" in
            /dev/spidev*|/dev/input/*|/dev/ttyS0|/dev/McuCom) exit 1 ;;
        esac
    done
done
test "$(hexdump -v -e '1/1 "%02x"' /sys/module/firmware_class/parameters/path)" = 0a
printf '%s\n' "$mounts"
echo CAP_RAM_ONLY_RESET_READY
