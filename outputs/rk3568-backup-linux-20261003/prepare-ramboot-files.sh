#!/system/bin/sh
# Create ordinary files in cache; never write a boot block device.
set -eu

root=/cache/rtctrl-linux-20261003
mkdir "$root"
chmod 700 "$root"

# Boot v2 has a 2048-byte page and a 33046536-byte uncompressed kernel.
# Read full pages, then remove only the kernel's alignment padding.
dd if=/dev/block/by-name/boot bs=2048 skip=1 count=16137 2>/dev/null |
    head -c 33046536 > "$root/Image"

cp /sys/firmware/fdt "$root/android-running.dtb"
cp /data/local/tmp/rtctrl-linux-userspace-20261003.cpio.gz \
    "$root/initramfs.cpio.gz"

sync
wc -c "$root/Image" "$root/android-running.dtb" "$root/initramfs.cpio.gz"
sha256sum "$root/Image" "$root/android-running.dtb" "$root/initramfs.cpio.gz"
