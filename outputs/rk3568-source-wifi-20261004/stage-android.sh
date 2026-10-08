#!/system/bin/sh
set -eu
work=/data/local/tmp/rtctrl-source-wifi-20261004
cache=/cache/rtctrl-source-wifi-20261004
previous=/cache/rtctrl-rcu-reset-20261004/Image
test "$(uname -r)" = 4.19.232
test ! -e "$cache"
test ! -L "$cache"
cd "$work"
sha256sum -c upload.sha256
printf '%s  %s\n' e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457 "$previous" | sha256sum -c -
mkdir "$cache"
cp "$previous" "$cache/Image"
cp wifi.dtb initramfs.cpio.gz upload.sha256 "$cache/"
chmod 600 "$cache/"*
sync
cd "$cache"
sha256sum -c upload.sha256
sha256sum Image
echo SOURCE_WIFI_RAM_BOOT_READY
