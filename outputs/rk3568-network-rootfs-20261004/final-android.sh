#!/system/bin/sh
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop sys.boot_completed)" = 1
id
uname -r
getprop sys.boot_completed
dumpsys battery
sha256sum /dev/block/by-name/boot /dev/block/by-name/uboot \
    /dev/block/by-name/trust /dev/block/by-name/dtbo /dev/block/by-name/vbmeta
printf '7 4 1 7\n' > /proc/sys/kernel/printk
cat /proc/sys/kernel/printk /proc/sys/kernel/kptr_restrict
sh /cache/rtctrl-network-rootfs-20261004/rootfs-check.sh android \
    /cache/rtctrl-network-rootfs-20261004/rootfs.img \
    32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3 \
    4.19.232 read
sync
echo ANDROID_RETURN_ROOTFS_READBACK_COMPLETE
