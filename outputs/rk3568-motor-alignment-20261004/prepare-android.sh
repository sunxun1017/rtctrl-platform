#!/system/bin/sh
# Stage new ordinary files; never write a startup partition.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-motor-alignment-20261004
cache=/cache/rtctrl-motor-alignment-20261004
test "$(readlink -f /cache)" = /cache
test ! -e "$cache"
test ! -L "$cache"
cd "$work"
sha256sum -c upload.sha256
mkdir "$cache"
chmod 700 "$cache"
for name in uart.dtb initramfs.cpio.gz linux-enumeration.sh linux-module-options.sh \
    linux-module-cleanup.sh rootfs-check.sh linux-rootfs-read.sh upload.sha256; do
    cp "$name" "$cache/$name"
    chmod 600 "$cache/$name"
done
sync
cd "$cache"
sha256sum -c upload.sha256
echo MOTOR_ALIGNMENT_INPUTS_STAGED
