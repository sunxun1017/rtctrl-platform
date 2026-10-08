#!/bin/sh
# Runs in RAM Linux. The only writable filesystem target is a new ordinary image.
set -eu
export PATH=/bin
cache_device=${1:?Pass the freshly verified cache device}
expected_release=${2:?Pass the exact source kernel release}
base=${cache_device##*/}
test "$(uname -r)" = "$expected_release"
test -b "$cache_device"
test "$(cat "/sys/class/block/$base/size")" = 786432
grep -qx 'PARTNAME=cache' "/sys/class/block/$base/uevent"
test -z "$(ls -A /mnt/cache)"
test -z "$(ls -A /mnt/root)"
cache_mounted=0
root_mounted=0
dev_mounted=0
proc_mounted=0
sys_mounted=0
root_pts_mounted=0
ram_pts_mounted=0
loop=
image=/mnt/cache/rtctrl-source-userspace-20261004/rootfs.ext4

cleanup() {
    failed=0
    if [ "$root_pts_mounted" = 1 ]; then
        if umount /mnt/root/dev/pts; then
            root_pts_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$sys_mounted" = 1 ]; then
        if umount /mnt/root/sys; then
            sys_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$proc_mounted" = 1 ]; then
        if umount /mnt/root/proc; then
            proc_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$dev_mounted" = 1 ] && [ "$failed" = 0 ]; then
        if umount /mnt/root/dev; then
            dev_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$root_mounted" = 1 ] && [ "$failed" = 0 ]; then
        sync
        if umount /mnt/root; then
            root_mounted=0
        else
            failed=1
        fi
    fi
    if [ -n "$loop" ] && [ "$failed" = 0 ]; then
        info=/sys/class/block/${loop##*/}/loop/backing_file
        if [ -r "$info" ]; then
            actual=$(cat "$info")
            if [ "$actual" = "$image" ] || [ "/$actual" = "$image" ]; then
                if losetup -d "$loop"; then
                    loop=
                else
                    failed=1
                fi
            else
                echo LOOP_OWNERSHIP_MISMATCH
                failed=1
            fi
        else
            loop=
        fi
    fi
    if [ "$cache_mounted" = 1 ] && [ "$failed" = 0 ]; then
        sync
        if umount /mnt/cache; then
            cache_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$ram_pts_mounted" = 1 ] && [ "$failed" = 0 ]; then
        if umount /dev/pts; then
            ram_pts_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$failed" != 0 ]; then
        echo USERSPACE_CLEANUP_FAILED_STAY_IN_RAM
        return 1
    fi
    echo USERSPACE_MOUNTS_RELEASED
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

# First open is read-only at the cache, loop and ext4 levels.
mount -t ext4 -o ro,noload "$cache_device" /mnt/cache
cache_mounted=1
test -f "$image"
test ! -L "$image"
test "$(stat -c %s "$image")" = 67108864
(
    cd /mnt/cache/rtctrl-source-userspace-20261004
    sha256sum -c rootfs.sha256
)
loop=$(losetup -f)
losetup -r "$loop" "$image"
mount -t ext4 -o ro,noload "$loop" /mnt/root
root_mounted=1
grep -q 'android-source-userspace-20261004' /mnt/root/var/lib/rtctrl/android-marker
cat /mnt/root/var/lib/rtctrl/android-marker
sha256sum /mnt/root/var/lib/rtctrl/android-marker
echo SOURCE_ROOTFS_READONLY_PASSED
cleanup

# Reopen independently for writes, never remount a read-only loop read-write.
mount -t ext4 -o rw "$cache_device" /mnt/cache
cache_mounted=1
loop=$(losetup -f)
losetup "$loop" "$image"
mount -t ext4 -o rw "$loop" /mnt/root
root_mounted=1
mount -t devpts -o mode=0600,ptmxmode=0666 devpts /dev/pts
ram_pts_mounted=1
mount --bind /dev /mnt/root/dev
dev_mounted=1
mount --bind /dev/pts /mnt/root/dev/pts
root_pts_mounted=1
mount -t proc proc /mnt/root/proc
proc_mounted=1
mount -t sysfs sysfs /mnt/root/sys
sys_mounted=1
chroot /mnt/root /bin/sh /usr/bin/check-base.sh "$expected_release"
printf 'source-linux-userspace-20261004\n' > /mnt/root/var/lib/rtctrl/linux-marker
sha256sum /mnt/root/var/lib/rtctrl/linux-marker
sync
cleanup
trap - EXIT HUP INT TERM
echo SOURCE_USERSPACE_TEST_COMPLETE
