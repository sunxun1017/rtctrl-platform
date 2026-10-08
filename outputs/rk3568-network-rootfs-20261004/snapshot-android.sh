#!/system/bin/sh
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
name=${1:?snapshot name}
case "$name" in
    after-android|after-linux) ;;
    *) exit 1 ;;
esac
image=/cache/rtctrl-network-rootfs-20261004/rootfs.img
output=/data/local/tmp/rtctrl-network-rootfs-20261004/rootfs-$name.img.gz
test -f "$image"
test ! -L "$image"
test ! -e "$output"
test ! -L "$output"
test -z "$(losetup -a | grep rtctrl-network-rootfs-20261004 || true)"
set -C
busybox gzip -1 -c "$image" > "$output"
sync
sha256sum "$image" "$output"
stat -c %s "$output"
echo ROOTFS_SNAPSHOT_READY
