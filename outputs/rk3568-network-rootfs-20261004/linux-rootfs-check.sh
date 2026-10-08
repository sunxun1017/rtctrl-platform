#!/bin/sh
# Run from RAM. First inspect cache read-only, then reopen for one marker.
set -eu
export PATH=/bin
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
expected_sha=${1:?SHA after Android marker}
test -z "$(losetup -a)"
test "$(cat /sys/class/block/mmcblk0p12/size)" = 786432
grep -qx PARTNAME=cache /sys/class/block/mmcblk0p12/uevent
test -z "$(ls -A /mnt/cache)"
mkdir -p /mnt/root /dev/pts
cache_mounted=0
pts_mounted=0
cleanup() {
    failed=0
    # A child/rootfs cleanup failure must keep its backing cache attached.
    if test -n "$(losetup -a)"; then
        echo LOOP_STILL_ATTACHED_STAY_IN_LINUX
        return 1
    fi
    if [ "$cache_mounted" = 1 ]; then
        sync
        if umount /mnt/cache; then
            cache_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$pts_mounted" = 1 ]; then
        if umount /dev/pts; then
            pts_mounted=0
        else
            failed=1
        fi
    fi
    return "$failed"
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
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
test -z "$(grep ' /dev/pts ' /proc/mounts || true)"
mount -t devpts -o mode=0600,ptmxmode=0666 devpts /dev/pts
pts_mounted=1
mount -t ext4 -o ro,noload /dev/mmcblk0p12 /mnt/cache
cache_mounted=1
image=/mnt/cache/rtctrl-network-rootfs-20261004/rootfs.img
sh /tmp/rootfs-check.sh linux "$image" "$expected_sha" \
    5.10.160-rt89-g9f9e9d18574d-dirty read
umount /mnt/cache
cache_mounted=0
mount -t ext4 -o rw /dev/mmcblk0p12 /mnt/cache
cache_mounted=1
sh /tmp/rootfs-check.sh linux "$image" "$expected_sha" \
    5.10.160-rt89-g9f9e9d18574d-dirty write
sha256sum "$image"
sync
cleanup
trap - EXIT HUP INT TERM
echo LINUX_NETWORK_ROOTFS_CHECK_COMPLETE
