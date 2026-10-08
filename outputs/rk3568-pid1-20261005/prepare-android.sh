#!/system/bin/sh
# Stage ordinary files in a fresh cache directory. No boot partition writes.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-pid1-20261005-v3
cache=/cache/rtctrl-pid1-20261005-v3
test "$(readlink -f /cache)" = /cache
test "$(readlink -f "$work")" = "$work"
test ! -e "$cache"
test ! -L "$cache"
cd "$work"
test ! -L upload.sha256
test -f upload.sha256
for name in rootfs-pid1.ext4 initramfs-pid1.cpio.gz uart.dtb prepare-android.sh; do
    test -f "$name"
    test ! -L "$name"
done
sha256sum -c upload.sha256
test "$(sha256sum /cache/rtctrl-rcu-reset-20261004/Image)" = 'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457  /cache/rtctrl-rcu-reset-20261004/Image'
space=$(df -k /cache)
set -- $space
test "$#" = 13
available=${11}
case "$available" in
    ''|*[!0-9]*) exit 1 ;;
esac
test "$available" -ge 21504
mkdir "$cache"
chmod 700 "$cache"
for name in rootfs-pid1.ext4 initramfs-pid1.cpio.gz uart.dtb prepare-android.sh upload.sha256; do
    cp "$name" "$cache/$name"
    chown 0:0 "$cache/$name"
    chmod 600 "$cache/$name"
done
sync
cd "$cache"
sha256sum -c upload.sha256
echo PID1_INPUTS_STAGED
