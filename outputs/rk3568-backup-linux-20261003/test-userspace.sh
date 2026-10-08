#!/system/bin/sh
# Run only inside a private mount namespace on the original Android kernel.
set -eu

root=/data/local/tmp/rtctrl-linux-userspace-20261003
archive=/data/local/tmp/rtctrl-linux-userspace-20261003.cpio.gz

busybox mount --make-rprivate /
mkdir -p "$root"
busybox mount -t tmpfs -o size=16m,mode=0755 tmpfs "$root"

cd "$root"
gzip -dc "$archive" |
    busybox cpio -idm

busybox mount -t proc -o ro,nosuid,nodev,noexec proc "$root/proc"
busybox mount -t sysfs -o ro,nosuid,nodev,noexec sysfs "$root/sys"

busybox chroot "$root" /bin/sh -c '
    set -eu
    export PATH=/bin
    echo MINIMAL_LINUX_USERSPACE_BEGIN
    echo "shell_pid=$$"
    /bin/busybox uname -m
    uname -r
    echo ROOT_CONTENTS
    ls /
    echo HOST_PID1_NAME
    cat /proc/1/comm
    echo MINIMAL_LINUX_USERSPACE_END
'

# All mounts disappear when the private mount namespace exits.
