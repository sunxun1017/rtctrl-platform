#!/system/bin/sh
# Stage ordinary files only; never write a boot partition or auto-start Linux.
set -eu

source_dir=/data/local/tmp/rtctrl-source-kernel-20261004
destination=/cache/rtctrl-source-kernel-20261004
test "$(getprop ro.build.version.release)" = 11
test "$(uname -r)" = 4.19.232
test ! -e "$destination"

sha256sum -c <<'CHECKSUMS'
c0efb3bb522005cf106500c26c5c2c02d5905c2bfa9ecb273c2663db20aad4ec  /data/local/tmp/rtctrl-source-kernel-20261004/Image
20c8f026b71fe4e8a8752a9407087eb05b4e4819b3fa7e2f4845be17727d8c15  /data/local/tmp/rtctrl-source-kernel-20261004/firstboot.dtb
2a97a6a3af2054417cd47459770629673a4655131a77c3a12dd8d30568854956  /cache/rtctrl-linux-20261003/initramfs.cpio.gz
CHECKSUMS

mkdir "$destination"
chmod 700 "$destination"
cp "$source_dir/Image" "$destination/Image"
cp "$source_dir/firstboot.dtb" "$destination/firstboot.dtb"
cp /cache/rtctrl-linux-20261003/initramfs.cpio.gz "$destination/initramfs.cpio.gz"
chmod 600 "$destination/Image" "$destination/firstboot.dtb" "$destination/initramfs.cpio.gz"

cd "$destination"
sha256sum Image firstboot.dtb initramfs.cpio.gz > SHA256SUMS
sync
sha256sum -c SHA256SUMS
wc -c Image firstboot.dtb initramfs.cpio.gz
