#!/system/bin/sh
# Read the original touch interface and full startup/rootfs fingerprints.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
echo ANDROID_CAP_BASELINE_BEGIN
uname -r
getprop ro.build.version.release
getprop sys.boot_completed
dumpsys battery
readlink -f /sys/bus/spi/devices/spi3.0/driver
readlink -f /sys/bus/spi/devices/spi3.0/of_node
cat /sys/bus/spi/devices/spi3.0/modalias
cat /proc/bus/input/devices
cat /sys/class/input/input0/capabilities/key
cat /sys/bus/spi/devices/spi3.0/statistics/messages
cat /sys/bus/spi/devices/spi3.0/statistics/errors
cat /sys/bus/spi/devices/spi3.0/statistics/timedout
cat /sys/kernel/debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins
sha256sum /dev/block/by-name/boot
sha256sum /dev/block/by-name/uboot
sha256sum /dev/block/by-name/trust
sha256sum /dev/block/by-name/dtbo
sha256sum /dev/block/by-name/vbmeta
sha256sum /cache/rtctrl-source-userspace-20261004/rootfs.ext4
sha256sum /cache/rtctrl-network-rootfs-20261004/rootfs.img
echo ANDROID_CAP_BASELINE_COMPLETE
