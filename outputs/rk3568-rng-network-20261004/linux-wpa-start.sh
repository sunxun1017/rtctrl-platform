#!/bin/sh
set -eu
sh /tmp/linux-rng-check.sh
state=/tmp/rtctrl-rng-network-20261004
test -d "$state"
test -f /tmp/wpa.conf
test ! -L /tmp/wpa.conf
test ! -e "$state/wpa.pid"
sed -i '/^update_config=/d' /tmp/wpa.conf
/bin/wpa_supplicant -i wlan0 -D nl80211 -c /tmp/wpa.conf \
    > "$state/wpa.log" 2>&1 &
printf '%s\n' "$!" > "$state/wpa.pid"
echo WPA_STARTED_AFTER_CRNG_READY
