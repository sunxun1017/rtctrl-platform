#!/system/bin/sh
# Stage new ordinary cache files, keeping startup partitions and old rootfs intact.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-audio-20261005
cache=/cache/rtctrl-audio-20261005
test "$(readlink -f /cache)" = /cache
test ! -e "$cache"
test ! -L "$cache"
cd "$work"
sha256sum -c upload.sha256
mkdir "$cache"
chmod 700 "$cache"
for name in audio.dtb alsa-inspect snd-soc-rk817.ko linux-interface.sh linux-return-guard.sh upload.sha256; do
    cp "$name" "$cache/$name"
    chmod 600 "$cache/$name"
done
sync
cd "$cache"
sha256sum -c upload.sha256
echo AUDIO_INPUTS_STAGED
