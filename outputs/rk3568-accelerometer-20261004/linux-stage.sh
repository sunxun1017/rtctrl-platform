#!/bin/sh
# Read only mount of cache and immediate release after copying files into RAM.
set -eu
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f62696e2f7368002f696e697400
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(cat /sys/class/block/mmcblk0p12/uevent | grep '^PARTNAME=')" = PARTNAME=cache
mkdir -p /tmp/accel-cache
mount -t ext4 -o ro,noload /dev/mmcblk0p12 /tmp/accel-cache
release_cache()
{
    cd /
    umount /tmp/accel-cache
}
trap release_cache EXIT
trap 'exit 1' HUP INT TERM
cd /tmp/accel-cache/rtctrl-accelerometer-20261004
sha256sum -c upload.sha256
mkdir /tmp/accel
cp accelerometer.dtb sensor_dev.ko mxc6655xa.ko sensor-inspect \
    linux-enumeration.sh linux-probe.sh linux-return-guard.sh upload.sha256 /tmp/accel/
cd /tmp/accel
sha256sum -c upload.sha256
chmod 700 sensor-inspect
cd /
umount /tmp/accel-cache
trap - EXIT HUP INT TERM
echo ACCEL_INPUTS_IN_RAM_CACHE_RELEASED
