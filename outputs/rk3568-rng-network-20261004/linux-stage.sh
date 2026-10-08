#!/bin/sh
# Copy checks into RAM from read-only cache, then release the block mount.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(cat /sys/class/block/mmcblk0p12/size)" = 786432
grep -qx PARTNAME=cache /sys/class/block/mmcblk0p12/uevent
test -z "$(losetup -a)"
test -z "$(grep ' /mnt/cache ' /proc/mounts || true)"
owned=0
release_cache() {
    if [ "$owned" = 1 ]; then
        cd / || return 1
        umount /mnt/cache
    fi
}
trap release_cache EXIT
trap 'exit 1' HUP INT TERM
mount -t ext4 -o ro,noload /dev/mmcblk0p12 /mnt/cache
owned=1
cd /mnt/cache/rtctrl-rng-network-20261004
sha256sum -c upload.sha256
for file in entropy-check linux-rng-check.sh linux-network-start.sh linux-wpa-start.sh linux-network-cleanup.sh upload.sha256; do
    test ! -e "/tmp/$file"
    test ! -L "/tmp/$file"
    cp "$file" "/tmp/$file"
done
chmod 700 /tmp/entropy-check
cd /tmp
sha256sum entropy-check linux-rng-check.sh linux-network-start.sh linux-wpa-start.sh linux-network-cleanup.sh
umount /mnt/cache
owned=0
trap - EXIT
trap - HUP INT TERM
test -z "$(grep ' /mnt/cache ' /proc/mounts || true)"
echo RNG_CHECK_INPUTS_IN_RAM_CACHE_RELEASED
