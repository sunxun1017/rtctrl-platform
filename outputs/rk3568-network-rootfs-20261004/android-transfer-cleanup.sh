#!/system/bin/sh
# Remove only the named RAM test directory, after checking the helper identity.
set -eu
test "$(id -u)" = 0
work=/dev/rtctrl-network-rootfs-20261004
helper=/data/local/tmp/rtctrl-network-rootfs-20261004-helper
test -d "$work"
test ! -L "$work"
if test -f "$work/server.pid"
then
    pid=$(cat "$work/server.pid")
    case "$pid" in
        ''|*[!0-9]*) exit 1 ;;
    esac
    if test -d "/proc/$pid"
    then
        test "$(readlink "/proc/$pid/exe")" = "$helper"
        kill "$pid"
        sleep 1
        test ! -d "/proc/$pid"
    fi
fi
rm -f "$work/transfer.bin" "$work/server.log" "$work/server.pid"
rmdir "$work"
echo ANDROID_TRANSFER_CLEANED
