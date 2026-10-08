#!/system/bin/sh
# Metadata and startup partition checks only. Do not open a sensor input node.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop sys.boot_completed)" = 1
echo ANDROID_ACCEL_BASELINE_BEGIN
uname -a
dumpsys battery
ls -ld /sys/bus/i2c/devices/5-0015
readlink -f /sys/bus/i2c/devices/5-0015/driver
cat /sys/bus/i2c/devices/5-0015/name
cat /proc/bus/input/devices
for node in /sys/class/input/input*; do
    printf '%s ' "$node"
    cat "$node/name"
    readlink -f "$node/device"
done
ls -l /dev/i2c-5 /dev/gsensor /dev/input 2>&1 || true
dmesg | grep -i -E 'mxc6655|gsensor|sensor.*initial' || true
for name in boot uboot trust dtbo vbmeta; do
    sha256sum "/dev/block/by-name/$name"
done
sha256sum /cache/rtctrl-source-userspace-20261004/rootfs.ext4
sha256sum /cache/rtctrl-network-rootfs-20261004/rootfs.img
echo ANDROID_ACCEL_BASELINE_COMPLETE
