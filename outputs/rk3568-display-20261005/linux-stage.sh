#!/bin/sh
# Copy verified diagnostic inputs into RAM, then release read-only cache.
set -eu
# The reviewed session creates this independent record before any stage checks.
test -f /tmp/display-stage-attempt
test ! -L /tmp/display-stage-attempt
test -f /tmp/display-return-guard.sh
test ! -L /tmp/display-return-guard.sh
test -f /tmp/display-stage.sh
test ! -L /tmp/display-stage.sh
attempt=$(cat /tmp/display-stage-attempt)
guard_fingerprint=$(sha256sum /tmp/display-return-guard.sh)
stage_fingerprint=$(sha256sum /tmp/display-stage.sh)
test "$attempt" = "display-stage-v2
$guard_fingerprint
$stage_fingerprint"
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f62696e2f7368002f696e697400
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
modules=$(cat /proc/modules)
test -z "$modules"
test ! -e /dev/McuCom
test ! -e /tmp/display
test ! -L /tmp/display
test ! -e /tmp/display-cache
test ! -L /tmp/display-cache
mounts=$(cat /proc/mounts)
while read -r source target kind rest; do
    case "$kind" in
        rootfs|devtmpfs|proc|sysfs|tmpfs) ;;
        *) exit 1 ;;
    esac
done <<EOF
$mounts
EOF
mkdir /tmp/display /tmp/display-cache
mounted=0
release_cache() {
    if test "$mounted" = 1; then
        cd / || return 1
        umount /tmp/display-cache || return 1
        mounted=0
    fi
}
trap release_cache EXIT
trap 'exit 1' HUP INT TERM
mount -t ext4 -o ro,noload /dev/mmcblk0p12 /tmp/display-cache
mounted=1
cd /tmp/display-cache/rtctrl-display-20261005-v1
sha256sum -c upload.sha256
cp Image display.dtb initramfs.cpio.gz linux-inspect.sh linux-return-guard.sh prepare-android.sh linux-stage.sh upload.sha256 /tmp/display/
cd /tmp/display
sha256sum -c upload.sha256
cd /
release_cache
trap - EXIT HUP INT TERM
printf 'display-stage-v2-complete\n' > /tmp/display/stage-complete
echo DISPLAY_INPUTS_IN_RAM_CACHE_RELEASED
