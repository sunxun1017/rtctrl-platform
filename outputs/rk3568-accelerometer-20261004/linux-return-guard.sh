#!/bin/sh
# Permit only this one-shot sensor pair to remain resident in RAM until reset.
# This deliberately does not exercise their known-unsafe generic remove path.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f62696e2f7368002f696e697400
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
test ! -e /dev/McuCom
test ! -e /sys/class/net/wlan0
loops=$(losetup -a)
test -z "$loops"
mounts=$(cat /proc/mounts)
test -n "$mounts"
printf '%s\n' "$mounts" |
    while read -r source point kind remainder; do
        case "$kind" in
            rootfs|devtmpfs|proc|sysfs|tmpfs) ;;
            *) exit 1 ;;
        esac
    done
modules=$(cat /proc/modules)
test -n "$modules"
module_count=0
for name in $(printf '%s\n' "$modules" | while read -r name remainder; do printf '%s\n' "$name"; done); do
    case "$name" in
        sensor_dev|mxc6655xa) ;;
        *) exit 1 ;;
    esac
    test "$(cat /sys/module/$name/initstate)" = live
    module_count=$((module_count + 1))
done
test "$module_count" = 2
outcome=$(cat /tmp/accel/outcome)
case "$outcome" in
    identity-off)
        test "$(readlink -f /sys/bus/i2c/devices/5-0015/driver)" = /sys/bus/i2c/drivers/gsensor_mxc6655
        /tmp/accel/sensor-inspect --require-off
        ;;
    probe-rejected)
        test ! -e /sys/bus/i2c/devices/5-0015/driver
        test ! -d /sys/bus/i2c/devices/5-0015/input
        test ! -e /dev/mma8452_daemon
        ;;
    *) exit 1 ;;
esac
for process in /proc/[0-9]*; do
    test -d "$process" || continue
    name=$(cat "$process/comm")
    case "$name" in
        wpa_supplicant|network-helper|sensor-inspect) exit 1 ;;
    esac
    for descriptor in "$process"/fd/*; do
        test -L "$descriptor" || continue
        target=$(readlink "$descriptor")
        case "$target" in
            /dev/i2c-*|/dev/input/*|/dev/mma8452_daemon|/dev/ttyS0|/dev/McuCom) exit 1 ;;
        esac
    done
done
firmware_path=$(hexdump -v -e '1/1 "%02x"' /sys/module/firmware_class/parameters/path)
test "$firmware_path" = 0a
printf '%s\n' "$mounts"
echo ACCEL_RAM_ONLY_RESET_READY_SENSOR_MODULES_RETAINED
