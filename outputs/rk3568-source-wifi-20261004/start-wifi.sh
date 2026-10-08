#!/bin/sh
# Minimal WPA build omits configuration writing, including update_config parser.
# The standard helper output is normalized before this exact source build reads it.
set -eu
test -f /tmp/wpa.conf
sed -i '/^update_config=/d' /tmp/wpa.conf
wpa_supplicant -i wlan0 -D nl80211 -c /tmp/wpa.conf > /tmp/wpa.log 2>&1 &
echo "$!" > /tmp/wpa.pid
