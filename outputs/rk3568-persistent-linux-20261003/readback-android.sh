#!/system/bin/sh
# Read the Linux marker in a private namespace without changing the image.
set -eu
image=/cache/rtctrl-linux-20261003/rootfs.ext4
point=/data/local/tmp/rtctrl-persistent-20261003/readback
if [ "${1:-}" != --worker ]; then
    test "$(uname -r)" = 4.19.232
    test "$(readlink -f "$image")" = "$image"
    test -f "$image"
    test ! -L "$image"
    test "$(stat -c %s "$image")" = 67108864
    exec unshare -m /system/bin/sh "$0" --worker
fi
busybox mount --make-rprivate /
mkdir -p "$point"
test -z "$(ls -A "$point")"
loop=
mounted=0
cleanup() {
    if [ "$mounted" = 1 ]; then
        umount "$point" || return 1
        mounted=0
    fi
    if [ -n "$loop" ]; then
        info="/sys/class/block/${loop##*/}/loop/backing_file"
        if [ -r "$info" ]; then
            actual=$(cat "$info")
            if [ "$actual" != "$image" ] && [ "/$actual" != "$image" ]; then
                echo 'Loop ownership mismatch; refusing detach'
                return 1
            fi
            losetup -d "$loop" || return 1
        fi
        loop=
    fi
}
trap 'cleanup' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
loop=$(losetup -frs "$image")
mount -t ext4 -o ro,noload "$loop" "$point"
mounted=1
cat "$point/var/lib/rtctrl/android-marker"
cat "$point/var/lib/rtctrl/linux-marker"
sha256sum "$point/var/lib/rtctrl/android-marker" "$point/var/lib/rtctrl/linux-marker"
cleanup
trap - EXIT HUP INT TERM
echo ANDROID_READBACK_CLEANUP_OK
