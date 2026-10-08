#!/bin/sh
# Called after the RAM kernel mounts the cache read-only with noload.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
work=/mnt/cache/rtctrl-rcu-reset-20261004
test -d "$work"
cd "$work"
sha256sum -c source-inputs.sha256
test ! -e /dev/pts/ptmx
mkdir -p /dev/pts
cleanup() {
    umount /dev/pts
}
mount -t devpts devpts /dev/pts
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
echo RCU_RESET_SOURCE_PROGRAMS_BEGIN
./codec-test
./pty-test
cleanup
trap - EXIT HUP INT TERM
echo RCU_RESET_SOURCE_PROGRAMS_PASSED
