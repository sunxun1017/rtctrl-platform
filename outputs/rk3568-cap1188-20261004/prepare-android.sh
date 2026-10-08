#!/system/bin/sh
# Stage new ordinary cache files, keeping startup partitions and old rootfs intact.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-cap1188-20261004
cache=/cache/rtctrl-cap1188-20261004
test "$(readlink -f /cache)" = /cache
test ! -e "$cache"
test ! -L "$cache"
cd "$work"
sha256sum -c upload.sha256
mkdir "$cache"
chmod 700 "$cache"
for name in cap1188-spi.dtb cap1188-inspect linux-enumeration.sh linux-identity.sh linux-return-guard.sh upload.sha256; do
    cp "$name" "$cache/$name"
    chmod 600 "$cache/$name"
done
sync
cd "$cache"
sha256sum -c upload.sha256
echo CAP_INPUTS_STAGED
