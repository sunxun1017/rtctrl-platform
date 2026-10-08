#!/system/bin/sh
set -eu
work=/data/local/tmp/rtctrl-persistent-20261003
cache=/cache/rtctrl-linux-20261003
image="$cache/rootfs.ext4"
new="$image.new"
point="$work/mount"

if [ "${1:-}" != --worker ]; then
    test "$(uname -r)" = 4.19.232
    test "$(readlink -f "$cache")" = "$cache"
    test ! -e "$image"
    test ! -e "$new"
    test -f "$work/rootfs.tar.gz"
    printf '%s  %s\n' \
        6bf3cba924359765b9848dc0638ba9a73fdea98994b89fb64ad39edb3bbc914d \
        "$work/rootfs.tar.gz" | sha256sum -c -
    exec unshare -m /system/bin/sh "$0" --worker
fi

busybox mount --make-rprivate /
mkdir -p "$point"
test -z "$(ls -A "$point")"
loop=
root_mounted=0
children=
cleanup() {
    failed=0
    for child in $children; do
        umount "$point/$child" || failed=1
    done
    children=
    if [ "$root_mounted" = 1 ] && [ "$failed" = 0 ]; then
        sync
        if umount "$point"; then
            root_mounted=0
        else
            failed=1
        fi
    fi
    if [ -n "$loop" ] && [ "$failed" = 0 ]; then
        backing_info="/sys/class/block/${loop##*/}/loop/backing_file"
        if [ ! -r "$backing_info" ]; then
            # Some loop setup tools request auto-clear when the last mount closes.
            loop=
        else
            actual=$(cat "$backing_info")
            if [ "$actual" = "$backing" ] || [ "/$actual" = "$backing" ]; then
            if losetup -d "$loop"; then
                loop=
            else
                failed=1
            fi
            else
                echo 'Loop ownership mismatch'
                failed=1
            fi
        fi
    fi
    return "$failed"
}
trap 'cleanup' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Only this new regular file is formatted. Never pass a physical block device.
truncate -s 67108864 "$new"
test -f "$new"
test ! -L "$new"
mke2fs -t ext4 -F -L rtctrl-root -O '^64bit,^metadata_csum' "$new"
backing="$new"
loop=$(losetup -fs "$backing")
test -b "$loop"
mount -t ext4 "$loop" "$point"
root_mounted=1
tar -xzf "$work/rootfs.tar.gz" -C "$point"

# Reuse only the module and two files actually observed on the original system.
cp /vendor/lib/modules/bcmdhd.ko "$point/lib/modules/4.19.232/bcmdhd.ko"
cp /vendor/etc/firmware/fw_bcm43456c5_ag.bin "$point/vendor/etc/firmware/"
cp /vendor/etc/firmware/nvram_ap6256.txt "$point/vendor/etc/firmware/"
(
    cd "$point"
    sha256sum \
        lib/modules/4.19.232/bcmdhd.ko \
        vendor/etc/firmware/fw_bcm43456c5_ag.bin \
        vendor/etc/firmware/nvram_ap6256.txt > etc/rtctrl/migration-files.sha256
)
cat "$point/etc/rtctrl/migration-files.sha256"

for child in dev proc sys; do
    mount --bind "/$child" "$point/$child"
    children="$child $children"
done
chroot "$point" /bin/sh /usr/bin/check-base.sh
chroot "$point" /bin/sh -c '
    export PATH=/bin
    set -e
    printf "android-baseline-20261003\n" > /var/lib/rtctrl/android-marker
    sha256sum /var/lib/rtctrl/android-marker
    sync
'
cleanup
mv "$new" "$image"
sync

# Reopen read-only: prove the marker survived unmount, not just a page-cache read.
backing="$image"
loop=$(losetup -frs "$backing")
mount -t ext4 -o ro,noload "$loop" "$point"
root_mounted=1
cat "$point/var/lib/rtctrl/android-marker"
sha256sum "$point/var/lib/rtctrl/android-marker"
cleanup
trap - EXIT HUP INT TERM
echo ANDROID_ROOTFS_READY
stat -c %s "$image"
ls -l "$image"
