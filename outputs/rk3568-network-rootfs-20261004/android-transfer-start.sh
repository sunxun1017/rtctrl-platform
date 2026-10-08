#!/system/bin/sh
# Android control: the exact source helper from the previous Linux RAM test.
set -eu
test "$(id -u)" = 0
work=/dev/rtctrl-network-rootfs-20261004
helper=/data/local/tmp/rtctrl-network-rootfs-20261004-helper
expected=b713e277bfcd25384975acb31253254b93bdad4a70e529b403368f6dbb4dc6f6
test ! -e "$work"
actual=$(sha256sum "$helper")
test "${actual%% *}" = "$expected"
if ss -ltn | grep -q ':18765 '
then
    echo TRANSFER_PORT_ALREADY_IN_USE
    exit 1
fi
mkdir -m 700 "$work"
"$helper" serve "$work/transfer.bin" > "$work/server.log" 2>&1 < /dev/null &
printf '%s\n' "$!" > "$work/server.pid"
sleep 1
cat "$work/server.log"
echo ANDROID_TRANSFER_STARTED
