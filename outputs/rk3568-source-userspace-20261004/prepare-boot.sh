#!/system/bin/sh
set -eu
work=/data/local/tmp/rtctrl-source-userspace-20261004
cache=/cache/rtctrl-source-userspace-20261004
test "$(uname -r)" = 4.19.232
test -f "$cache/rootfs.ext4"
test ! -L "$cache"
test ! -e "$cache/Image"
test ! -e "$cache/firstboot.dtb"
test ! -e "$cache/initramfs.cpio.gz"
cd "$work"
sha256sum -c boot-inputs.sha256
cp Image firstboot.dtb initramfs.cpio.gz boot-inputs.sha256 "$cache/"
chmod 600 "$cache/Image" "$cache/firstboot.dtb" "$cache/initramfs.cpio.gz" "$cache/boot-inputs.sha256"
sync
cd "$cache"
sha256sum -c boot-inputs.sha256
echo SOURCE_BOOT_FILES_READY
