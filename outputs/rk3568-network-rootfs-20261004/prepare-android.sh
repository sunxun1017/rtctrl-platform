#!/system/bin/sh
# Stage a new ordinary cache file; all earlier experiments are retained.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-network-rootfs-20261004
cache=/cache/rtctrl-network-rootfs-20261004
test "$(readlink -f /cache)" = /cache
test ! -e "$cache"
test "$(stat -c %s "$work/rootfs.img")" = 67108864
printf '%s  %s\n' \
    fb998ec342e19d28df0dc7ba1f24171c4f9cb651b4a1150045ed5d3c3c6ba757 \
    "$work/rootfs.img" | sha256sum -c -
mkdir "$cache"
chmod 700 "$cache"
cp "$work/rootfs.img" "$cache/rootfs.img"
cp "$work/rootfs-check.sh" "$cache/rootfs-check.sh"
cp "$work/linux-rootfs-check.sh" "$cache/linux-rootfs-check.sh"
chmod 600 "$cache/rootfs.img" "$cache/rootfs-check.sh" "$cache/linux-rootfs-check.sh"
sync
printf '%s  %s\n' \
    fb998ec342e19d28df0dc7ba1f24171c4f9cb651b4a1150045ed5d3c3c6ba757 \
    "$cache/rootfs.img" | sha256sum -c -
sh "$cache/rootfs-check.sh" android "$cache/rootfs.img" \
    fb998ec342e19d28df0dc7ba1f24171c4f9cb651b4a1150045ed5d3c3c6ba757 \
    4.19.232 all
sha256sum "$cache/rootfs.img" > "$cache/android-image.sha256"
sync
echo ANDROID_NETWORK_ROOTFS_READY
