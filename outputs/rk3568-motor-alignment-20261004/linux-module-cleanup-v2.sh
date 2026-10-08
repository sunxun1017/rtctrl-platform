#!/bin/sh
# Attempt every independent cleanup; any failure keeps the board in Linux.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
state=/tmp/rtctrl-motor-module-options
test -d "$state"
test ! -L "$state"
test ! -e /tmp/wpa.conf
processes=$(ps)
case "$processes" in
    *wpa_supplicant*|*network-helper*) exit 1 ;;
esac
failed=0
if test -e /sys/class/net/wlan0; then
    ip addr flush dev wlan0 || failed=1
    ip link set wlan0 down || failed=1
fi
modules=$(cat /proc/modules) || failed=1
case "$modules" in
    bcmdhd\ *|*'
bcmdhd '*) rmmod bcmdhd || failed=1 ;;
esac
if test -e "$state/config-owned"; then
    if test ! -e /lib/firmware/config-uart-stage.txt; then
        rm "$state/config-owned" || failed=1
    elif test ! -L /lib/firmware/config-uart-stage.txt &&
        content=$(cat /lib/firmware/config-uart-stage.txt) &&
        [ "$content" = "$(printf 'PM=0\nband=a\n')" ]; then
        if rm /lib/firmware/config-uart-stage.txt; then
            rm "$state/config-owned" || failed=1
        else
            failed=1
        fi
    else
        failed=1
    fi
fi
if test -e "$state/firmware-path-owned"; then
    if current=$(cat /sys/module/firmware_class/parameters/path) &&
        previous=$(cat "$state/firmware-class-path") &&
        [ "$current" = /lib/firmware ]; then
        if printf '%s\n' "$previous" > /sys/module/firmware_class/parameters/path &&
            restored=$(cat /sys/module/firmware_class/parameters/path) &&
            [ "$restored" = "$previous" ]; then
            rm "$state/firmware-path-owned" "$state/firmware-class-path" || failed=1
        else
            failed=1
        fi
    else
        failed=1
    fi
fi
test ! -e /sys/class/net/wlan0 || failed=1
modules=$(cat /proc/modules) || failed=1
case "$modules" in
    bcmdhd\ *|*'
bcmdhd '*) failed=1 ;;
esac
test ! -e /lib/firmware/config-uart-stage.txt || failed=1
remaining=$(ls -A "$state") || failed=1
test -z "$remaining" || failed=1
if [ "$failed" != 0 ]; then
    echo MODULE_CLEANUP_INCOMPLETE_STAY_IN_LINUX
    exit 1
fi
echo MODULE_CONFIG_AND_FIRMWARE_PATH_RELEASED
