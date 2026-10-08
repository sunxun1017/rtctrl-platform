#!/system/bin/sh
# Stage one ordinary helper file. Never reboot or flash from this script.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-normal-reboot-20261005-v1
cache=/cache/rtctrl-normal-reboot-20261005-v1
test "$(readlink -f "$work")" = "$work"
test "$(readlink -f /cache)" = /cache
test ! -e "$cache"
test ! -L "$cache"
test -f "$work/normal-reboot"
test ! -L "$work/normal-reboot"
test "$(sha256sum "$work/normal-reboot")" = "6c90fe3dca1f0ae6ffab50eddbfdccca27cc2f8ccf0821814456ae3980fe09f5  $work/normal-reboot"
mkdir "$cache"
chmod 700 "$cache"
cp "$work/normal-reboot" "$cache/normal-reboot"
chmod 600 "$cache/normal-reboot"
sync
test "$(sha256sum "$cache/normal-reboot")" = "6c90fe3dca1f0ae6ffab50eddbfdccca27cc2f8ccf0821814456ae3980fe09f5  $cache/normal-reboot"
echo NORMAL_REBOOT_HELPER_STAGED_NO_REBOOT
