#!/system/bin/sh
# $1 is an existing private temporary transfer directory, not a block device.
set -eu
root="$1/extra"
mkdir "$root"
chmod 700 "$root"

for name in security misc baseparameter smdt
do
    dd if="/dev/block/by-name/$name" of="$root/$name.img" bs=1048576
done

dd if=/dev/block/mmcblk2 of="$root/loader-head.bin" bs=512 count=8192
dd if=/dev/block/mmcblk2 of="$root/gpt-tail.bin" bs=512 skip=122126303 count=33
dd if=/dev/block/mmcblk2boot0 of="$root/mmcblk2boot0.img" bs=1048576
dd if=/dev/block/mmcblk2boot1 of="$root/mmcblk2boot1.img" bs=1048576
cp /sys/firmware/fdt "$root/android-running.dtb"
cp /proc/config.gz "$root/kernel.config.gz"

cd "$root"
sha256sum ./*.img ./*.bin android-running.dtb kernel.config.gz > SHA256SUMS
cat SHA256SUMS
wc -c ./*.img ./*.bin android-running.dtb kernel.config.gz
busybox tar -czf "$1/extra-startup.tar.gz" .
sha256sum "$1/extra-startup.tar.gz"
wc -c "$1/extra-startup.tar.gz"
