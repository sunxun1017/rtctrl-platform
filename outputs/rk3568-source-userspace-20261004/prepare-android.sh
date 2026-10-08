#!/system/bin/sh
# New ordinary file only. No old rootfs, module, firmware or partition writes.
set -eu
work=/data/local/tmp/rtctrl-source-userspace-20261004
cache=/cache/rtctrl-source-userspace-20261004
point="$work/mount"
image="$cache/rootfs.ext4"
backing="$image.new"
if [ "${1:-}" != --worker ]; then
    test "$(uname -r)" = 4.19.232
    test "$(getprop sys.boot_completed)" = 1
    test "$(readlink -f /cache)" = /cache
    test ! -e "$cache"
    printf '%s  %s\n' \
        81c751c33fb79be0d1e94be770dce155dfd3f380f0cacfe4afaa5778d8be7243 \
        "$work/rootfs.tar.gz" | sha256sum -c -
    exec unshare -m /system/bin/sh "$0" --worker
fi
busybox mount --make-rprivate /
mkdir "$cache"
chmod 700 "$cache"
mkdir "$point"
test -z "$(ls -A "$point")"
loop=
mounted=0
children=
cleanup() {
    failed=0
    for child in $children; do
        if ! umount "$point/$child"; then
            failed=1
        fi
    done
    if [ "$failed" = 0 ]; then
        children=
    fi
    if [ "$mounted" = 1 ] && [ "$failed" = 0 ]; then
        sync
        if umount "$point"; then
            mounted=0
        else
            failed=1
        fi
    fi
    if [ -n "$loop" ] && [ "$failed" = 0 ]; then
        info=/sys/class/block/${loop##*/}/loop/backing_file
        if [ -r "$info" ]; then
            actual=$(cat "$info")
            if [ "$actual" != "$backing" ] && [ "/$actual" != "$backing" ]; then
                echo LOOP_OWNERSHIP_MISMATCH
                return 1
            fi
            losetup -d "$loop" || return 1
        fi
        loop=
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
truncate -s 67108864 "$backing"
test -f "$backing"
test ! -L "$backing"
mke2fs -t ext4 -F -L rtctrl-source -O '^64bit,^metadata_csum' "$backing"
loop=$(losetup -fs "$backing")
mount -t ext4 "$loop" "$point"
mounted=1
tar -xzf "$work/rootfs.tar.gz" -C "$point"
mount --bind /dev "$point/dev"
children=dev
mount --bind /dev/pts "$point/dev/pts"
children="dev/pts $children"
mount -t proc proc "$point/proc"
children="proc $children"
mount -t sysfs sysfs "$point/sys"
children="sys $children"
chroot "$point" /bin/sh /usr/bin/check-base.sh 4.19.232
printf 'android-source-userspace-20261004\n' > "$point/var/lib/rtctrl/android-marker"
sha256sum "$point/var/lib/rtctrl/android-marker"
sync
cleanup
mv "$backing" "$image"
backing="$image"
sync
(
    cd "$cache"
    sha256sum rootfs.ext4 > rootfs.sha256
)
chmod 600 "$image" "$cache/rootfs.sha256"
loop=$(losetup -frs "$backing")
mount -t ext4 -o ro,noload "$loop" "$point"
mounted=1
cat "$point/var/lib/rtctrl/android-marker"
sha256sum "$point/var/lib/rtctrl/android-marker"
cleanup
trap - EXIT HUP INT TERM
echo ANDROID_SOURCE_ROOTFS_READY
