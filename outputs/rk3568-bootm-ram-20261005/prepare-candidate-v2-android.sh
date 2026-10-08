#!/system/bin/sh
set -eu

work=/data/local/tmp/rtctrl-bootm-candidate-20261005-v2
cache=/cache/rtctrl-bootm-ram-20261005-v1
source=$work/boot-linux-ram-v2.img
dest=$cache/boot-linux-ram-v2.img
sha=67f351b822887c5e2fae10c099760a126d20daee2e9b2931b945a1176af37dbe
original=$cache/boot-original.img
original_sha=0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28
rootfs=/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4
rootfs_sha=3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d

test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
test -d "$work"
test ! -L "$work"
test "$(realpath "$work")" = "$work"
test "$(stat -c '%u:%g' "$work")" = 0:0
test -f "$source"
test ! -L "$source"
test "$(realpath "$source")" = "$source"
test "$(stat -c '%u:%g:%h:%s' "$source")" = 0:0:1:41943040
test "$(sha256sum "$source")" = "$sha  $source"

test -d "$cache"
test ! -L "$cache"
test "$(realpath "$cache")" = "$cache"
test "$(stat -c '%u:%g:%a' "$cache")" = 0:0:700
test -f "$original"
test ! -L "$original"
test "$(stat -c '%u:%g:%h:%s' "$original")" = 0:0:1:41943040
test "$(sha256sum "$original")" = "$original_sha  $original"
test -f "$rootfs"
test ! -L "$rootfs"
test "$(realpath "$rootfs")" = "$rootfs"
test "$(stat -c '%u:%g:%h:%s' "$rootfs")" = 0:0:1:16777216
test "$(sha256sum "$rootfs")" = "$rootfs_sha  $rootfs"
test ! -e "$dest"
test ! -L "$dest"
available=$(df -k /cache | tail -n 1 | awk '{ print $4 }')
test "$available" -ge 49152
df -k /cache

cp "$source" "$dest"
chmod 400 "$dest"
test -f "$dest"
test ! -L "$dest"
test "$(realpath "$dest")" = "$dest"
test "$(stat -c '%u:%g:%h:%s' "$dest")" = 0:0:1:41943040
test "$(sha256sum "$dest")" = "$sha  $dest"
sync
test "$(sha256sum "$dest")" = "$sha  $dest"
test "$(sha256sum "$original")" = "$original_sha  $original"
test "$(sha256sum "$rootfs")" = "$rootfs_sha  $rootfs"
df -k /cache
echo LINUX_BOOT_V2_40MIB_CACHED_SHA_VERIFIED_RAM_ONLY_NO_FLASH
