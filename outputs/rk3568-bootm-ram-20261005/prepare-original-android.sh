#!/system/bin/sh
set -eu

work=/data/local/tmp/rtctrl-bootm-original-20261005-v1
cache=/cache/rtctrl-bootm-ram-20261005-v1
source=$work/boot-original.img
dest=$cache/boot-original.img
sha=0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28

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

test -d /cache
test ! -L /cache
test ! -e "$cache"
test ! -L "$cache"
available=$(df -k /cache | tail -n 1 | awk '{ print $4 }')
test "$available" -ge 49152
df -k /cache

mkdir -m 700 "$cache"
test "$(realpath "$cache")" = "$cache"
test "$(stat -c '%u:%g' "$cache")" = 0:0
cp "$source" "$dest"
chmod 400 "$dest"
test -f "$dest"
test ! -L "$dest"
test "$(realpath "$dest")" = "$dest"
test "$(stat -c '%u:%g:%h:%s' "$dest")" = 0:0:1:41943040
test "$(sha256sum "$dest")" = "$sha  $dest"
sync
test "$(sha256sum "$dest")" = "$sha  $dest"
df -k /cache
echo ORIGINAL_BOOT_40MIB_CACHED_SHA_VERIFIED_NO_FLASH
