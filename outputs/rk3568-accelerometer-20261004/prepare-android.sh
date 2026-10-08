#!/system/bin/sh
# Copy new ordinary cache files; never change a boot partition or prior artifacts.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-accelerometer-20261004
cache=/cache/rtctrl-accelerometer-20261004
test "$(readlink -f /cache)" = /cache
test ! -e "$cache"
test ! -L "$cache"
cd "$work"
sha256sum -c upload.sha256
mkdir "$cache"
chmod 700 "$cache"
for name in accelerometer.dtb sensor_dev.ko mxc6655xa.ko sensor-inspect \
    linux-enumeration.sh linux-probe.sh linux-return-guard.sh upload.sha256; do
    cp "$name" "$cache/$name"
    chmod 600 "$cache/$name"
done
sync
cd "$cache"
sha256sum -c upload.sha256
echo ACCEL_INPUTS_STAGED
