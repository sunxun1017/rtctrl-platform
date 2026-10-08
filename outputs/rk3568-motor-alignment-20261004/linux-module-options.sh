#!/bin/sh
# Verify real module option delivery; no WLAN authentication in this check.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test ! -e /sys/class/net/wlan0
test -z "$(grep '^bcmdhd ' /proc/modules || true)"
test ! -e /tmp/wpa.conf
/bin/entropy-check --check
printf '%s  %s\n' \
    cbf55f844b59a57fb4ff67c1754df09dcee716a6385dbb463cce1ae846e4d956 \
    /lib/modules/bcmdhd.ko | sha256sum -c -
printf '%s  %s\n' \
    06d3bebe4b193b5db97b7f99bde94e2e85ca95dc35677079ecf86f8f9b0eb734 \
    /lib/firmware/fw_bcm43456c5_ag.bin | sha256sum -c -
printf '%s  %s\n' \
    c36643f35c32b9248bbb34870a3ab152237907713e999533592acd925dd04410 \
    /lib/firmware/nvram_ap6256.txt | sha256sum -c -
state=/tmp/rtctrl-motor-module-options
test ! -e "$state"
test ! -L "$state"
test ! -e /lib/firmware/config-uart-stage.txt
test ! -L /lib/firmware/config-uart-stage.txt
mkdir "$state"
(
    set -C
    printf 'PM=0\nband=a\n' > /lib/firmware/config-uart-stage.txt
)
touch "$state/config-owned"
printf /lib/firmware > /sys/module/firmware_class/parameters/path
insmod /lib/modules/bcmdhd.ko \
    firmware_path=/lib/firmware/fw_bcm43456c5_ag.bin \
    nvram_path=/lib/firmware/nvram_ap6256.txt \
    config_path=/lib/firmware/config-uart-stage.txt
test "$(cat /sys/module/bcmdhd/parameters/firmware_path)" = /lib/firmware/fw_bcm43456c5_ag.bin
test "$(cat /sys/module/bcmdhd/parameters/nvram_path)" = /lib/firmware/nvram_ap6256.txt
cat /sys/module/bcmdhd/parameters/firmware_path
cat /sys/module/bcmdhd/parameters/nvram_path
ip link set wlan0 up
grep -q DRIVER=bcmsdh_sdmmc /sys/bus/sdio/devices/*/uevent
dmesg | grep -E 'config-uart-stage.txt|PM = 0|band = 1'
dmesg | grep -q 'config-uart-stage.txt'
dmesg | grep -q 'PM = 0'
dmesg | grep -q 'band = 1'
echo REAL_BUSYBOX_MODULE_OPTIONS_DELIVERED
