#!/bin/sh
# New ordinary ext4 file only. PID1 stays outside this short-lived chroot.
set -eu
mode=${1:?android or linux}
image=${2:?absolute image filename}
expected_sha=${3:?current complete image SHA-256}
release=${4:?expected kernel release}
action=${5:-all}
case "$action" in
    all|read|write) ;;
    *) exit 1 ;;
esac
case "$mode" in
    android)
        test "$(uname -r)" = 4.19.232
        test "$(getprop sys.boot_completed)" = 1
        exec unshare -m /system/bin/sh "$0" android-worker "$image" "$expected_sha" "$release" "$action"
        ;;
    android-worker)
        busybox mount --make-rprivate /
        point=/dev/rtctrl-network-rootfs-20261004-root
        ram_tmp=/dev/rtctrl-network-rootfs-20261004-tmp
        mkdir -p "$point" "$ram_tmp"
        chmod 1777 "$ram_tmp"
        marker=android-marker
        marker_value=android-network-rootfs-20261004
        ;;
    linux)
        export PATH=/bin
        point=/mnt/root
        ram_tmp=/tmp
        marker=linux-marker
        marker_value=source-linux-network-rootfs-20261004
        ;;
    *) exit 1 ;;
esac
test "$(uname -r)" = "$release"
test -f "$image"
test ! -L "$image"
test "$(readlink -f "$image")" = "$image"
test "$(stat -c %s "$image")" = 67108864
test -d "$point"
test ! -L "$point"
test -z "$(ls -A "$point")"
test -d "$ram_tmp"
test ! -L "$ram_tmp"
printf '%s  %s\n' "$expected_sha" "$image" | sha256sum -c -

loop=
root_mounted=0
dev_mounted=0
pts_mounted=0
proc_mounted=0
sys_mounted=0
tmp_mounted=0
probe_owned=0
cleanup() {
    failed=0
    if [ "$probe_owned" = 1 ]; then
        if rm -f "$ram_tmp/rtctrl-rootfs-ram-probe"; then
            probe_owned=0
        else
            failed=1
        fi
    fi
    if [ "$tmp_mounted" = 1 ]; then
        if umount "$point/tmp"; then
            tmp_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$pts_mounted" = 1 ]; then
        if umount "$point/dev/pts"; then
            pts_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$sys_mounted" = 1 ]; then
        if umount "$point/sys"; then
            sys_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$proc_mounted" = 1 ]; then
        if umount "$point/proc"; then
            proc_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$dev_mounted" = 1 ] && [ "$failed" = 0 ]; then
        if umount "$point/dev"; then
            dev_mounted=0
        else
            failed=1
        fi
    fi
    if [ "$root_mounted" = 1 ] && [ "$failed" = 0 ]; then
        sync
        if umount "$point"; then
            root_mounted=0
        else
            failed=1
        fi
    fi
    if [ -n "$loop" ] && [ "$failed" = 0 ]; then
        backing=/sys/class/block/${loop##*/}/loop/backing_file
        if test -r "$backing"; then
            actual=$(cat "$backing")
            if [ "$actual" != "$image" ] && [ "/$actual" != "$image" ]; then
                echo LOOP_OWNERSHIP_MISMATCH
                return 1
            fi
            if losetup -d "$loop"; then
                loop=
            else
                failed=1
            fi
        else
            loop=
        fi
    fi
    if [ "$failed" != 0 ]; then
        echo ROOTFS_CLEANUP_FAILED_STAY_IN_CURRENT_SYSTEM
        return 1
    fi
    echo ROOTFS_MOUNTS_RELEASED
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

# Read-only at both loop and filesystem levels. RAM /tmp is explicitly bound.
if [ "$action" != write ]; then
loop=$(losetup -f)
losetup -r "$loop" "$image"
mount -t ext4 -o ro,noload "$loop" "$point"
root_mounted=1
mount --bind /dev "$point/dev"
dev_mounted=1
mount --bind /dev/pts "$point/dev/pts"
pts_mounted=1
mount -t proc proc "$point/proc"
proc_mounted=1
mount -t sysfs sysfs "$point/sys"
sys_mounted=1
mount --bind "$ram_tmp" "$point/tmp"
tmp_mounted=1
chroot "$point" /bin/sha256sum -c /etc/rtctrl/payload.sha256
chroot "$point" /bin/sh /usr/bin/check-base.sh "$release"
chroot "$point" /usr/bin/wpa_supplicant -v
chroot "$point" /usr/bin/wpa_cli -v
if [ "$mode" = linux ]; then
    test "$(cat "$point/var/lib/rtctrl/android-marker")" = \
        android-network-rootfs-20261004
    sha256sum "$point/var/lib/rtctrl/android-marker"
fi
if [ -e "$point/var/lib/rtctrl/linux-marker" ]; then
    test "$(cat "$point/var/lib/rtctrl/linux-marker")" = \
        source-linux-network-rootfs-20261004
    sha256sum "$point/var/lib/rtctrl/linux-marker"
    echo LINUX_MARKER_READ_BACK
fi
test ! -e "$ram_tmp/rtctrl-rootfs-ram-probe"
test ! -L "$ram_tmp/rtctrl-rootfs-ram-probe"
probe_owned=1
chroot "$point" /bin/sh -c 'set -C
printf ram-only > /tmp/rtctrl-rootfs-ram-probe'
test "$(cat "$ram_tmp/rtctrl-rootfs-ram-probe")" = ram-only
rm -f "$ram_tmp/rtctrl-rootfs-ram-probe"
probe_owned=0
cleanup
printf '%s  %s\n' "$expected_sha" "$image" | sha256sum -c -
echo ROOTFS_READONLY_AND_RAM_TMP_PASSED
fi
if [ "$action" = read ]; then
    trap - EXIT HUP INT TERM
    echo ROOTFS_READ_CHECK_COMPLETE
    exit 0
fi

# Reopen independently for the single named persistent marker.
loop=$(losetup -f)
losetup "$loop" "$image"
mount -t ext4 -o rw "$loop" "$point"
root_mounted=1
test ! -e "$point/var/lib/rtctrl/$marker"
(
    set -C
    printf '%s\n' "$marker_value" > "$point/var/lib/rtctrl/$marker"
)
sha256sum "$point/var/lib/rtctrl/$marker"
sync
cleanup

loop=$(losetup -f)
losetup -r "$loop" "$image"
mount -t ext4 -o ro,noload "$loop" "$point"
root_mounted=1
test "$(cat "$point/var/lib/rtctrl/$marker")" = "$marker_value"
sha256sum "$point/var/lib/rtctrl/$marker"
cleanup
trap - EXIT HUP INT TERM
echo ROOTFS_SOURCE_CHECK_COMPLETE
