#!/system/bin/sh
# New ordinary cache inputs only, prior tested files remain untouched.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop sys.boot_completed)" = 1
work=/data/local/tmp/rtctrl-rng-network-20261004
cache=/cache/rtctrl-rng-network-20261004
test "$(readlink -f /cache)" = /cache
test ! -e "$cache"
(
    cd "$work"
    sha256sum -c upload.sha256
)
mkdir "$cache"
chmod 700 "$cache"
for name in wifi-rng.dtb entropy-check linux-rng-check.sh linux-network-start.sh \
    linux-wpa-start.sh linux-network-cleanup.sh upload.sha256; do
    cp "$work/$name" "$cache/$name"
    chmod 600 "$cache/$name"
done
sync
(
    cd "$cache"
    sha256sum -c upload.sha256
)
echo RNG_NETWORK_NEW_CACHE_INPUTS_READY
