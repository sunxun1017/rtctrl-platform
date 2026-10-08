#!/bin/sh
# Module/firmware setup only. Authentication follows after fresh CRNG check.
set -eu
mode=${1:-default}
case "$mode" in
    default|pm0) ;;
    *) exit 1 ;;
esac
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test ! -e /sys/class/net/wlan0
test -z "$(grep '^bcmdhd ' /proc/modules || true)"
test ! -e /tmp/wpa.conf
test ! -L /tmp/wpa.conf
sh /tmp/linux-rng-check.sh
printf '%s  %s\n' \
    cbf55f844b59a57fb4ff67c1754df09dcee716a6385dbb463cce1ae846e4d956 \
    /lib/modules/bcmdhd.ko | sha256sum -c -
printf '%s  %s\n' \
    06d3bebe4b193b5db97b7f99bde94e2e85ca95dc35677079ecf86f8f9b0eb734 \
    /lib/firmware/fw_bcm43456c5_ag.bin | sha256sum -c -
printf '%s  %s\n' \
    c36643f35c32b9248bbb34870a3ab152237907713e999533592acd925dd04410 \
    /lib/firmware/nvram_ap6256.txt | sha256sum -c -
state=/tmp/rtctrl-rng-network-20261004
if test -d "$state"; then
    test ! -L "$state"
    test -z "$(ls -A "$state")"
else
    mkdir "$state"
fi
printf '%s\n' "$mode" > "$state/mode"
printf /lib/firmware > /sys/module/firmware_class/parameters/path
if [ "$mode" = pm0 ]; then
    test ! -e /lib/firmware/config.txt
    test ! -L /lib/firmware/config.txt
    (
        set -C
        printf 'PM=0\nband=a\n' > /lib/firmware/config.txt
    )
    touch "$state/pm0-owned"
    insmod /lib/modules/bcmdhd.ko
else
    insmod /lib/modules/bcmdhd.ko
fi
ip link set wlan0 up
grep -q '^bcmdhd ' /proc/modules
grep -q DRIVER=bcmsdh_sdmmc /sys/bus/sdio/devices/*/uevent
echo WIFI_DEVICE_READY_FOR_AUTHENTICATION
