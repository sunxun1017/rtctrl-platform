#!/system/bin/sh
set -eu
test "$(uname -r)" = 4.19.232
id
uname -r
getprop sys.boot_completed
dumpsys battery
ip -4 addr show wlan0
ip -4 route show
for function in /sys/bus/sdio/devices/*; do
    cat "$function/uevent"
    readlink "$function/driver" || true
done
sha256sum /vendor/etc/firmware/fw_bcm43456c5_ag.bin /vendor/etc/firmware/nvram_ap6256.txt
for part in boot uboot trust dtbo vbmeta; do
    sha256sum "/dev/block/by-name/$part"
done
cat /proc/sys/kernel/printk
cat /proc/sys/kernel/kptr_restrict
echo ANDROID_WIFI_BASELINE_COMPLETE
