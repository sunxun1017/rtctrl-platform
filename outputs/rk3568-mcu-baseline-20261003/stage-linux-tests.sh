#!/system/bin/sh
# Ordinary files only: no partition formatting, boot-image or environment write.
set -eu

destination=/cache/rtctrl-linux-source-tests-20261003
if [ -e "$destination" ]; then
    echo 'Refusing an existing source-test directory' >&2
    exit 1
fi

mkdir "$destination"
chmod 700 "$destination"
cp /data/local/tmp/rtctrl-patchx-codec-test-20261003 "$destination/codec-test"
cp /data/local/tmp/rtctrl-patchx-pty-test-20261003 "$destination/pty-test"
cp /data/local/tmp/rtctrl-read-mcu-cache-20261003 "$destination/read-cached-mcu-info"
cp /data/local/tmp/rtctrl-run-linux-source-tests-20261003.sh "$destination/run-tests.sh"
chmod 700 "$destination/codec-test" "$destination/pty-test" \
    "$destination/read-cached-mcu-info" "$destination/run-tests.sh"

cd "$destination"
sha256sum codec-test pty-test read-cached-mcu-info run-tests.sh > SHA256SUMS
chmod 600 SHA256SUMS
cat /proc/sys/kernel/printk > printk-before.txt
sync
sha256sum -c SHA256SUMS
