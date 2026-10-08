#!/bin/sh
# Existing tool rootfs is read-only at cache, loop and ext4 levels.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(cat /sys/class/block/mmcblk0p12/size)" = 786432
grep -qx PARTNAME=cache /sys/class/block/mmcblk0p12/uevent
test -z "$(losetup -a)"
test -z "$(grep ' /mnt/cache ' /proc/mounts || true)"
test -z "$(grep ' /dev/pts ' /proc/mounts || true)"
cache_mounted=0
pts_mounted=0
cleanup() {
    cd / || return 1
    if test -n "$(losetup -a)"; then
        echo LOOP_REMAINS_KEEP_CACHE_MOUNTED
        return 1
    fi
    if [ "$cache_mounted" = 1 ]; then
        umount /mnt/cache || return 1
        cache_mounted=0
    fi
    if [ "$pts_mounted" = 1 ]; then
        umount /dev/pts || return 1
        pts_mounted=0
    fi
}
on_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    if ! cleanup; then
        status=1
    fi
    exit "$status"
}
trap on_exit EXIT
trap 'exit 1' HUP INT TERM
mount -t devpts -o mode=0600,ptmxmode=0666 devpts /dev/pts
pts_mounted=1
mount -t ext4 -o ro,noload /dev/mmcblk0p12 /mnt/cache
cache_mounted=1
sh /tmp/rootfs-check.sh linux \
    /mnt/cache/rtctrl-network-rootfs-20261004/rootfs.img \
    32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3 \
    5.10.160-rt89-g9f9e9d18574d-dirty read
cleanup
trap - EXIT HUP INT TERM
echo CODEC_PTY_AND_READONLY_ROOTFS_PASSED
