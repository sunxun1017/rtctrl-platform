#!/bin/sh
# Every metadata read must succeed before the reset step is made available.
set -eu
release=$(uname -r)
test "$release" = 5.10.160-rt89-g9f9e9d18574d-dirty
test ! -e /lib/firmware/config-uart-stage.txt
test ! -e /tmp/wpa.conf
test ! -e /sys/class/net/wlan0
modules=$(cat /proc/modules)
case "$modules" in
    bcmdhd\ *|*'
bcmdhd '*) exit 1 ;;
esac
processes=$(ps)
case "$processes" in
    *wpa_supplicant*|*network-helper*) exit 1 ;;
esac
loops=$(losetup -a)
test -z "$loops"
firmware_path=$(hexdump -v -e '1/1 "%02x"' /sys/module/firmware_class/parameters/path)
test "$firmware_path" = 0a
mounts=$(cat /proc/mounts)
test -n "$mounts"
printf '%s\n' "$mounts" |
    while read -r source point kind remainder; do
        case "$kind" in
            rootfs|devtmpfs|proc|sysfs|tmpfs) ;;
            *) exit 1 ;;
        esac
    done
if test -d /tmp/rtctrl-motor-module-options; then
    remaining=$(ls -A /tmp/rtctrl-motor-module-options)
    test -z "$remaining"
fi
printf '%s\n' "$mounts"
echo UART_FD_SNAPSHOT_BEST_EFFORT
ls -l /proc/[0-9]*/fd/* 2>/dev/null | grep ' -> /dev/ttyS0$' || true
echo RAM_ONLY_RESOURCES_RELEASED
