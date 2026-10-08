#!/bin/sh
# Copy the reboot-only helper to RAM; this script never requests a reboot.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
test "$(cat /tmp/display/outcome)" = interface-verified
test ! -e /tmp/normal-reboot
test ! -L /tmp/normal-reboot
test ! -e /tmp/normal-reboot-cache
test ! -L /tmp/normal-reboot-cache
mkdir /tmp/normal-reboot-cache
mounted=0
release_cache() {
    if test "$mounted" = 1; then
        cd / || return 1
        umount /tmp/normal-reboot-cache || return 1
        mounted=0
    fi
}
trap release_cache EXIT
trap 'exit 1' HUP INT TERM
mount -t ext4 -o ro,noload /dev/mmcblk0p12 /tmp/normal-reboot-cache
mounted=1
file=/tmp/normal-reboot-cache/rtctrl-normal-reboot-20261005-v1/normal-reboot
test -f "$file"
test ! -L "$file"
test "$(sha256sum "$file")" = "6c90fe3dca1f0ae6ffab50eddbfdccca27cc2f8ccf0821814456ae3980fe09f5  $file"
cp "$file" /tmp/normal-reboot
test "$(sha256sum /tmp/normal-reboot)" = '6c90fe3dca1f0ae6ffab50eddbfdccca27cc2f8ccf0821814456ae3980fe09f5  /tmp/normal-reboot'
chmod 500 /tmp/normal-reboot
release_cache
trap - EXIT HUP INT TERM
echo NORMAL_REBOOT_HELPER_VERIFIED_IN_RAM_CACHE_RELEASED
