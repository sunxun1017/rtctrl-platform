#!/system/bin/sh
set -eu
id
uname -r
getprop sys.boot_completed
getprop init.svc.adbd
getprop service.adb.tcp.port
dumpsys battery
ip -4 addr show wlan0
ip -4 route show table all
cat /proc/net/arp
cat /proc/net/wireless
ss -ltn
sha256sum /vendor/etc/firmware/fw_bcm43456c5_ag.bin
sha256sum /vendor/etc/firmware/nvram_ap6256.txt
sha256sum /dev/block/by-name/boot
sha256sum /dev/block/by-name/uboot
sha256sum /dev/block/by-name/trust
sha256sum /dev/block/by-name/dtbo
sha256sum /dev/block/by-name/vbmeta
cat /proc/sys/kernel/printk
cat /proc/sys/kernel/kptr_restrict
echo ANDROID_NETWORK_BASELINE_COMPLETE
