#!/bin/sh
set -eu
export PATH=/bin
echo ROOTFS_BASELINE_BEGIN
test "$(uname -m)" = aarch64
test "$(uname -r)" = 4.19.232
test -x /bin/busybox
test -d /var/lib/rtctrl
for applet in chroot mount umount losetup sync reboot sha256sum stat; do
    test -L "/bin/$applet"
done
uname -r
ls /
sha256sum /bin/busybox
echo ROOTFS_BASELINE_END
