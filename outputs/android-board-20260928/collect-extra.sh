#!/system/bin/sh
set -u
umask 077
out=/data/local/tmp/rtctrl-hw-20260928/extra
mkdir "$out" || exit 2
capture() { name=$1; shift; "$@" > "$out/$name.txt" 2>&1; printf '%s\t%s\n' "$name" "$?" >> "$out/status.tsv"; }
capture identity sh -c 'id; uname -a; getenforce; for p in ro.product.model ro.product.board ro.hardware ro.build.version.release ro.build.version.sdk ro.build.version.security_patch ro.build.fingerprint ro.bootloader; do echo "$p=$(getprop "$p")"; done'
capture cpu cat /proc/cpuinfo
capture memory cat /proc/meminfo
capture partitions sh -c 'cat /proc/partitions; ls -l /dev/block/by-name; for p in /sys/class/block/mmcblk2*; do echo "$p"; cat "$p/start" "$p/size" "$p/partition" 2>/dev/null; done'
capture modules sh -c 'cat /proc/modules; find /vendor/lib/modules /odm/lib/modules -type f 2>/dev/null'
capture buses sh -c 'for bus in i2c spi sdio usb; do echo "BUS=$bus"; for d in /sys/bus/$bus/devices/*; do [ -e "$d" ] || continue; echo "$d"; for a in name modalias vendor device idVendor idProduct product; do [ ! -f "$d/$a" ] || { echo "$a:"; cat "$d/$a"; }; done; readlink "$d/driver"; readlink -f "$d/of_node"; done; done'
capture serial sh -c 'ls -l /dev/ttyS* /dev/ttyFIQ*; for d in /sys/class/tty/ttyS*; do echo "$d"; readlink -f "$d/device"; readlink -f "$d/device/of_node"; done'
capture audio sh -c 'cat /proc/asound/cards /proc/asound/pcm; ls -l /dev/snd'
capture input cat /proc/bus/input/devices
capture video sh -c 'for d in /sys/class/video4linux/*; do echo "$d"; cat "$d/name"; readlink -f "$d/device"; done; ls -l /dev/media*'
capture display sh -c 'for d in /sys/class/drm/*; do [ ! -f "$d/status" ] || { echo "$d"; cat "$d/status" "$d/modes"; }; done; for d in /sys/class/backlight/*; do echo "$d"; cat "$d/brightness" "$d/max_brightness"; done'
capture firmware-list sh -c 'ls -l /vendor/firmware /vendor/etc/firmware /lib/firmware /system/etc/firmware'
capture kernel-log dmesg
echo __EXTRA_DONE__
