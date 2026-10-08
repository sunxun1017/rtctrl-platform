#!/system/bin/sh
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
id
uname -r
getprop ro.build.version.release
getprop sys.boot_completed
dumpsys battery
echo STARTUP_HASHES
for partition in boot uboot trust dtbo vbmeta; do
    sha256sum "/dev/block/by-name/$partition"
done
echo ORIGINAL_ROOTFS_HASH
sha256sum /cache/rtctrl-network-rootfs-20261004/rootfs.img
echo KERNEL_DIAGNOSTIC_SETTINGS
cat /proc/sys/kernel/printk /proc/sys/kernel/kptr_restrict
echo MOTOR_FIRMWARE_DOWNLOAD_DIRECTORY_METADATA
ls -ld /sdcard/Android/data/com.patchx_main/files/downloads 2>/dev/null || true
ls -l /sdcard/Android/data/com.patchx_main/files/downloads 2>/dev/null || true
echo ANDROID_RETURN_AND_STARTUP_FINGERPRINTS_READ_COMPLETE
