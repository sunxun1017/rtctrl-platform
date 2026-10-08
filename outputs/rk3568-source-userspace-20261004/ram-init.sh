#!/bin/sh
export PATH=/bin
mount -t devtmpfs devtmpfs /dev
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t tmpfs tmpfs /tmp
mkdir -p /mnt/cache /mnt/root /dev/pts
echo 'Source Linux userspace test: PID1 remains in RAM'
uname -r
while :; do
    setsid cttyhack /bin/sh </dev/console >/dev/console 2>&1
    sleep 1
done
