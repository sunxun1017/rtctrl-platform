#!/bin/sh
# Inspect this RAM boot without opening a sensor, UART, or calibration interface.
set -eu
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f62696e2f7368002f696e697400
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
test ! -e /dev/McuCom
test ! -d /sys/bus/i2c/devices/5-0062
echo LINUX_ACCEL_ENUMERATION_BEGIN
cat /proc/cmdline
cat /proc/modules
ls -ld /sys/bus/i2c/devices/5-0015
cat /sys/bus/i2c/devices/5-0015/name
readlink -f /sys/bus/i2c/devices/5-0015/of_node
test ! -e /sys/bus/i2c/devices/5-0015/driver
ls -l /dev/i2c-5
cat /proc/bus/input/devices
cat /proc/tty/driver/serial
test "$(cat /sys/firmware/devicetree/base/i2c@fe5e0000/status)" = okay
test "$(cat /sys/firmware/devicetree/base/i2c@fe5e0000/mxc6655xa@15/compatible)" = gs_mxc6655xa
mkdir -p /tmp/accel-debug
mount -t debugfs debugfs /tmp/accel-debug
trap 'umount /tmp/accel-debug' EXIT
trap 'exit 1' HUP INT TERM
grep -E 'pin (16|17|107|108) ' /tmp/accel-debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins
umount /tmp/accel-debug
trap - EXIT HUP INT TERM
echo LINUX_ACCEL_UNBOUND_NODE_AND_BUS_VERIFIED
