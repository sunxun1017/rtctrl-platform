#!/system/bin/sh
# Reopen the new file read-only in a private mount namespace after returning.
set -eu
image=/cache/rtctrl-source-userspace-20261004/rootfs.ext4
point=/data/local/tmp/rtctrl-source-userspace-20261004/readback
if [ "${1:-}" != --worker ]; then
    test "$(uname -r)" = 4.19.232
    test "$(getprop sys.boot_completed)" = 1
    test "$(readlink -f "$image")" = "$image"
    test -f "$image"
    test ! -L "$image"
    test "$(stat -c %s "$image")" = 67108864
    exec unshare -m /system/bin/sh "$0" --worker
fi
busybox mount --make-rprivate /
mkdir "$point"
test -z "$(ls -A "$point")"
loop=
mounted=0
cleanup() {
    if [ "$mounted" = 1 ]; then
        umount "$point" || return 1
        mounted=0
    fi
    if [ -n "$loop" ]; then
        info=/sys/class/block/${loop##*/}/loop/backing_file
        if [ -r "$info" ]; then
            actual=$(cat "$info")
            if [ "$actual" != "$image" ] && [ "/$actual" != "$image" ]; then
                echo LOOP_OWNERSHIP_MISMATCH
                return 1
            fi
            losetup -d "$loop" || return 1
        fi
        loop=
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
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
loop=$(losetup -frs "$image")
mount -t ext4 -o ro,noload "$loop" "$point"
mounted=1
cat "$point/var/lib/rtctrl/android-marker" "$point/var/lib/rtctrl/linux-marker"
sha256sum "$point/var/lib/rtctrl/android-marker" "$point/var/lib/rtctrl/linux-marker"
cleanup
trap - EXIT HUP INT TERM
echo ANDROID_SOURCE_READBACK_CLEANUP_OK
