#!/bin/sh
# Copy experiment scripts to RAM and release the read-only cache mount.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(cat /sys/class/block/mmcblk0p12/size)" = 786432
grep -qx PARTNAME=cache /sys/class/block/mmcblk0p12/uevent
test -z "$(grep ' /mnt/cache ' /proc/mounts || true)"
test -z "$(losetup -a)"
owned=0
on_exit() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$owned" = 1 ]; then
        cd / || status=1
        umount /mnt/cache || status=1
    fi
    exit "$status"
}
trap on_exit EXIT
trap 'exit 1' HUP INT TERM
mount -t ext4 -o ro,noload /dev/mmcblk0p12 /mnt/cache
owned=1
cd /mnt/cache/rtctrl-motor-alignment-20261004
sha256sum -c upload.sha256
for name in linux-enumeration.sh linux-module-options.sh linux-module-cleanup.sh \
    rootfs-check.sh linux-rootfs-read.sh; do
    test ! -e "/tmp/$name"
    test ! -L "/tmp/$name"
    cp "$name" "/tmp/$name"
done
cd /
umount /mnt/cache
owned=0
trap - EXIT HUP INT TERM
test -z "$(grep ' /mnt/cache ' /proc/mounts || true)"
echo MOTOR_ALIGNMENT_SCRIPTS_IN_RAM_CACHE_RELEASED
