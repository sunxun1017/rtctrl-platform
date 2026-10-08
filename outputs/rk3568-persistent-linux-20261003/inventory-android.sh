#!/system/bin/sh
# Read metadata only. No device ioctls, sampling, module changes, or library loading.
set -u
out=/data/local/tmp/rtctrl-persistent-20261003
mkdir -p "$out/inventory"
chmod 700 "$out"

capture() {
    name=$1
    shift
    "$@" > "$out/inventory/$name.txt" 2>&1
    result=$?
    printf '%s\t%s\n' "$name" "$result" >> "$out/inventory/status.tsv"
}

: > "$out/inventory/status.tsv"
capture kernel uname -a
capture modules cat /proc/modules
capture filesystem cat /proc/filesystems
capture mounts cat /proc/mounts
capture module-load cat /vendor/lib/modules/modules.load
capture module-dep cat /vendor/lib/modules/modules.dep
capture wifi-parameters sh -c '
    for file in /sys/module/bcmdhd/parameters/*path*; do
        printf "%s: " "$file"
        cat "$file"
    done
'
capture wifi-firmware-log sh -c '
    dmesg | grep -E "fw_path|fw path|nvram|clm_path|Firmware:|Firmware version|Final.*path|firmware.*bin|4359"
'
capture bindings sh -c '
    for node in \
        /sys/bus/sdio/devices/* \
        /sys/bus/i2c/devices/5-0062 \
        /sys/bus/i2c/devices/5-0015 \
        /sys/bus/spi/devices/spi3.0; do
        printf "%s: " "$node"
        readlink "$node/driver"
    done
'
capture devices sh -c '
    ls -l /dev/ttySMT* /dev/mali* /dev/dri/* /dev/rknpu* /dev/snd/*
    ls -l /sys/class/drm /sys/class/watchdog
'
capture audio cat /proc/asound/cards
capture video sh -c '
    for node in /sys/class/video4linux/*; do
        printf "%s: " "$node"
        cat "$node/name"
    done
'
capture input cat /proc/bus/input/devices
capture npu sh -c '
    ls /sys/kernel/debug/rknpu
    for file in /sys/kernel/debug/rknpu/version /sys/kernel/debug/rknpu/load; do
        printf "%s: " "$file"
        cat "$file"
    done
'
capture library-usage sh -c '
    for file in /proc/[0-9]*/maps; do
        grep -E "librknn|librga|libmpp|libmali|librkaiq|lib.*serial" "$file" |
            sed "s|^|$file: |"
    done
'
capture storage sh -c '
    cat /sys/class/block/mmcblk2p12/uevent
    cat /sys/class/block/mmcblk2p12/size
    df -k /cache
    losetup -a
'

cd "$out"
tar -czf inventory.tar.gz inventory
sha256sum inventory.tar.gz
wc -c inventory.tar.gz
