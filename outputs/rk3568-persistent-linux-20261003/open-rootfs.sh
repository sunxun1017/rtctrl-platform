#!/bin/sh
# Run in the RAM Linux shell only, after inspecting the current partition map.
set -eu
export PATH=/bin
device=${1:?Pass the verified cache block device}
base=${device##*/}
test -b "$device"
test "$(cat "/sys/class/block/$base/size")" = 786432
grep -qx 'PARTNAME=cache' "/sys/class/block/$base/uevent"
test -z "$(ls -A /mnt/cache)"
test -z "$(ls -A /mnt/root)"
cache_mounted=0
root_mounted=0
dev_mounted=0
proc_mounted=0
sys_mounted=0
loop=

cleanup() {
    result=0
    if [ "$sys_mounted" = 1 ]; then
        if umount /mnt/root/sys; then sys_mounted=0; else result=1; fi
    fi
    if [ "$proc_mounted" = 1 ]; then
        if umount /mnt/root/proc; then proc_mounted=0; else result=1; fi
    fi
    if [ "$dev_mounted" = 1 ]; then
        if umount /mnt/root/dev; then dev_mounted=0; else result=1; fi
    fi
    if [ "$root_mounted" = 1 ] && [ "$result" = 0 ]; then
        sync
        if umount /mnt/root; then root_mounted=0; else result=1; fi
    fi
    if [ -n "$loop" ] && [ "$result" = 0 ]; then
        backing_info="/sys/class/block/${loop##*/}/loop/backing_file"
        if [ ! -r "$backing_info" ]; then
            loop=
        else
            owned=$(cat "$backing_info")
            if [ "$owned" = "$image" ] || [ "/$owned" = "$image" ]; then
                if losetup -d "$loop"; then
                    loop=
                else
                    result=1
                fi
            else
                echo 'Loop ownership differs; refusing detach'
                result=1
            fi
        fi
    fi
    if [ "$cache_mounted" = 1 ] && [ "$result" = 0 ]; then
        sync
        if umount /mnt/cache; then cache_mounted=0; else result=1; fi
    fi
    if [ "$result" = 0 ]; then
        sync
        echo 'ROOTFS_CLEANUP_OK'
    else
        echo 'ROOTFS_CLEANUP_FAILED: remain in RAM; do not reboot'
    fi
    return "$result"
}

trap 'cleanup' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
mount -t ext4 -o rw "$device" /mnt/cache
cache_mounted=1
image=/mnt/cache/rtctrl-linux-20261003/rootfs.ext4
test -f "$image"
test ! -L "$image"
test "$(stat -c %s "$image")" = 67108864
loop=$(losetup -f)
case "$loop" in
    /dev/loop[0-9]*) ;;
    *) echo 'Unexpected loop device'; exit 1 ;;
esac
if ! losetup "$loop" "$image"; then
    loop=
    exit 1
fi
backing=$(cat "/sys/class/block/${loop##*/}/loop/backing_file")
test "$backing" = "$image" || test "/$backing" = "$image"
mount -t ext4 -o rw "$loop" /mnt/root
root_mounted=1
mount --bind /dev /mnt/root/dev
dev_mounted=1
mount -t proc proc /mnt/root/proc
proc_mounted=1
mount -t sysfs sysfs /mnt/root/sys
sys_mounted=1
echo "ROOTFS_ENTER loop=$loop image=$image"
chroot /mnt/root /bin/sh
echo 'ROOTFS_CHILD_EXITED'
cleanup
trap - EXIT HUP INT TERM
