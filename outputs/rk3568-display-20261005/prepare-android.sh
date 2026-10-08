#!/system/bin/sh
# Copy verified ordinary inputs into one new cache directory. Never flash.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-display-20261005-v1
cache=/cache/rtctrl-display-20261005-v1
test "$(readlink -f /cache)" = /cache
test "$(readlink -f "$work")" = "$work"
test ! -e "$cache"
test ! -L "$cache"
cd "$work"
test ! -L upload.sha256
test -f upload.sha256
for name in Image display.dtb initramfs.cpio.gz linux-inspect.sh linux-return-guard.sh prepare-android.sh linux-stage.sh; do
    test -f "$name"
    test ! -L "$name"
done
sha256sum -c upload.sha256
space=$(df -k /cache)
set -- $space
test "$#" = 13
available=${11}
case "$available" in
    ''|*[!0-9]*) exit 1 ;;
esac
test "$available" -ge 40960
mkdir "$cache"
chmod 700 "$cache"
for name in Image display.dtb initramfs.cpio.gz linux-inspect.sh linux-return-guard.sh prepare-android.sh linux-stage.sh upload.sha256; do
    cp "$name" "$cache/$name"
    chmod 600 "$cache/$name"
done
sync
cd "$cache"
sha256sum -c upload.sha256
echo DISPLAY_INPUTS_STAGED
