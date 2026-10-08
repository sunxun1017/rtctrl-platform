#!/bin/sh
# One-shot load of patched source drivers. No input open, enable, or calibration.
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
test ! -e /sys/bus/i2c/devices/5-0015/driver
test ! -e /tmp/accel/probe-attempted
modules=$(cat /proc/modules)
test -z "$modules"
cd /tmp/accel
sha256sum -c upload.sha256
echo LINUX_ACCEL_DRIVER_LOAD_BEGIN
insmod /tmp/accel/sensor_dev.ko
test "$(cat /sys/module/sensor_dev/initstate)" = live
touch /tmp/accel/probe-attempted
insmod /tmp/accel/mxc6655xa.ko
test "$(cat /sys/module/mxc6655xa/initstate)" = live
cat /proc/modules
dmesg | grep -E 'mxc6655|sensor_probe|sensor_chip_init|i2c.*(timeout|NACK|error)' || true
cat /proc/bus/input/devices
if test -e /sys/bus/i2c/devices/5-0015/driver; then
    test "$(readlink -f /sys/bus/i2c/devices/5-0015/driver)" = /sys/bus/i2c/drivers/gsensor_mxc6655
    /tmp/accel/sensor-inspect --require-off
    printf '%s\n' identity-off > /tmp/accel/outcome
    echo LINUX_ACCEL_IDENTITY_AND_DEFAULT_OFF_VERIFIED
else
    test ! -d /sys/bus/i2c/devices/5-0015/input
    test ! -e /dev/mma8452_daemon
    printf '%s\n' probe-rejected > /tmp/accel/outcome
    echo LINUX_ACCEL_PROBE_REJECTED_NO_FALSE_BINDING
fi
echo LINUX_ACCEL_DIAGNOSTIC_COMPLETE_NO_SAMPLING
