#!/bin/sh
# Stop only recorded test processes; leave the board running on any failure.
set -eu
state=/tmp/rtctrl-rng-network-20261004
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test -d "$state"
test ! -L "$state"
stop_owned() {
    file=$1
    executable=$2
    if test ! -e "$file"; then
        return 0
    fi
    pid=$(cat "$file") || return 1
    case "$pid" in
        ''|*[!0-9]*|0|1) return 1 ;;
    esac
    if test -d "/proc/$pid"; then
        actual=$(readlink -f "/proc/$pid/exe") || return 1
        if [ "$actual" != "$executable" ]; then
            echo PROCESS_OWNERSHIP_MISMATCH
            return 1
        fi
        kill -TERM "$pid" || return 1
        count=0
        while test -d "/proc/$pid" && [ "$count" -lt 5 ]; do
            sleep 1 || return 1
            count=$((count + 1))
        done
        if test -d "/proc/$pid"; then
            return 1
        fi
    fi
    rm -f "$file"
}
failed=0
if ! stop_owned "$state/server.pid" /bin/network-helper; then
    failed=1
fi
if ! stop_owned "$state/wpa.pid" /bin/wpa_supplicant; then
    failed=1
fi
if ! rm -f /tmp/wpa.conf; then
    failed=1
fi
if test -e /sys/class/net/wlan0; then
    if ! ip addr flush dev wlan0; then
        failed=1
    fi
    if ! ip link set wlan0 down; then
        failed=1
    fi
fi
if grep -q '^bcmdhd ' /proc/modules; then
    if ! rmmod bcmdhd; then
        failed=1
    fi
fi
if test -e "$state/pm0-owned"; then
    if test ! -e /lib/firmware/config.txt; then
        rm -f "$state/pm0-owned" || failed=1
    elif [ "$(cat /lib/firmware/config.txt)" = "$(printf 'PM=0\nband=a\n')" ]; then
        if rm -f /lib/firmware/config.txt; then
            rm -f "$state/pm0-owned" || failed=1
        else
            failed=1
        fi
    else
        failed=1
    fi
fi
test ! -e /tmp/wpa.conf || failed=1
test ! -e /sys/class/net/wlan0 || failed=1
test -z "$(grep '^bcmdhd ' /proc/modules || true)" || failed=1
test -z "$(ps | grep -E '[w]pa_supplicant|[n]etwork-helper' || true)" || failed=1
if [ "$failed" != 0 ]; then
    echo WIFI_CLEANUP_INCOMPLETE_STAY_IN_LINUX
    exit 1
fi
rm -f "$state/mode" "$state/wpa.log" "$state/server.log" "$state/transfer.bin"
test -z "$(ls -A "$state")"
echo WIFI_CREDENTIAL_PROCESSES_MODULE_AND_INTERFACE_RELEASED
