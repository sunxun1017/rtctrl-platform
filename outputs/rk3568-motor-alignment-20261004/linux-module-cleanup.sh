#!/bin/sh
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
state=/tmp/rtctrl-motor-module-options
test -d "$state"
test ! -L "$state"
test ! -e /tmp/wpa.conf
test -z "$(ps | grep -E '[w]pa_supplicant|[n]etwork-helper' || true)"
if test -e /sys/class/net/wlan0; then
    ip addr flush dev wlan0
    ip link set wlan0 down
fi
if grep -q '^bcmdhd ' /proc/modules; then
    rmmod bcmdhd
fi
test ! -e /sys/class/net/wlan0
test -z "$(grep '^bcmdhd ' /proc/modules || true)"
if test -e "$state/config-owned"; then
    if test -e /lib/firmware/config-uart-stage.txt; then
        test ! -L /lib/firmware/config-uart-stage.txt
        test "$(cat /lib/firmware/config-uart-stage.txt)" = "$(printf 'PM=0\nband=a\n')"
        rm /lib/firmware/config-uart-stage.txt
    fi
    rm "$state/config-owned"
fi
test ! -e /lib/firmware/config-uart-stage.txt
test -z "$(ls -A "$state")"
echo MODULE_AND_TEST_CONFIG_RELEASED
