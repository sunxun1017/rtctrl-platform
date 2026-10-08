#!/bin/sh
# Run only in the independently booted, verified original 4.19 RAM Linux.
set -eu
export PATH=/bin

cache_device=${1:?Pass the freshly verified cache block device}
block_name=${cache_device##*/}
cache_mount=/mnt/cache
cache_mounted=0
pts_mounted=0

cleanup() {
    result=$?
    failed=0
    trap - EXIT HUP INT TERM

    if [ "$pts_mounted" -eq 1 ]; then
        if ! umount /dev/pts; then
            failed=1
        fi
    fi

    if [ "$cache_mounted" -eq 1 ]; then
        if ! umount "$cache_mount"; then
            failed=1
        fi
    fi

    if [ "$failed" -ne 0 ]; then
        echo "SOURCE_TEST_CLEANUP_FAILED; inspect mounts before reboot"
        exit 1
    fi

    echo "SOURCE_TEST_MOUNTS_RELEASED"
    exit "$result"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

test "$(uname -r)" = 4.19.232
test -b "$cache_device"
test "$(cat "/sys/class/block/$block_name/size")" = 786432
grep -qx 'PARTNAME=cache' "/sys/class/block/$block_name/uevent"
test -z "$(ls -A "$cache_mount")"

# noload also prevents journal replay; SHA checks reject stale/inconsistent data.
mount -t ext4 -o ro,noload "$cache_device" "$cache_mount"
cache_mounted=1
tests_dir=$cache_mount/rtctrl-linux-source-tests-20261003
test -d "$tests_dir"

(
    cd "$tests_dir"
    sha256sum -c SHA256SUMS
)

mkdir -p /dev/pts
mount -t devpts -o mode=0600,ptmxmode=0666 devpts /dev/pts
pts_mounted=1

echo 'SOURCE_TEST_OS=independent-original-kernel-Linux'
cat /proc/1/cmdline
echo
"$tests_dir/codec-test"
"$tests_dir/pty-test"
"$tests_dir/read-cached-mcu-info" /dev/McuCom
echo 'LINUX_SOURCE_TESTS_PASSED'
