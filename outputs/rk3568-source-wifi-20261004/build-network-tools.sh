#!/bin/sh
# Run from project root. Upstream sources, static AArch64 WPA2-PSK tools.
set -eu
export PATH="$PWD/.deps/host-tools/bin:$PATH"
out="$PWD/outputs/rk3568-source-wifi-20261004"
archives="$PWD/.deps/wifi-source"
build="$out/build/userspace"
test ! -e "$build"
mkdir -p "$build"
printf '%s\n' \
    '912ea06f74e30a8e36fbb68064d6cdff218d8d591db0fc5d75dee6c81ac7fc0a  wpa_supplicant-2.11.proxy.tar.gz' \
    '2a56e1edefa3e68a7c00879496736fdbf62fc94ed3232c0baba127ecfa76874d  libnl-3.11.0.proxy.tar.gz' \
    > "$build/archives.sha256"
cd "$archives"
sha256sum -c "$build/archives.sha256"
tar -xzf libnl-3.11.0.proxy.tar.gz -C "$build"
tar -xzf wpa_supplicant-2.11.proxy.tar.gz -C "$build"

cd "$build/libnl-3.11.0"
./configure --host=aarch64-linux-gnu --prefix="$build/prefix" \
    --disable-shared --enable-static --disable-cli
make -j4
make install

cd "$build/wpa_supplicant-2.11/wpa_supplicant"
cat > .config <<EOF
CONFIG_DRIVER_NL80211=y
CONFIG_LIBNL32=y
CONFIG_CTRL_IFACE=y
CONFIG_BACKEND=file
CONFIG_NO_CONFIG_WRITE=y
CONFIG_NO_CONFIG_BLOBS=y
CONFIG_NO_EAP=y
CONFIG_IEEE80211W=y
CONFIG_TLS=internal
CONFIG_INTERNAL_LIBTOMMATH=y
CFLAGS += -I$build/prefix/include/libnl3
LDFLAGS += -static -L$build/prefix/lib
EOF
export PKG_CONFIG_LIBDIR="$build/prefix/lib/pkgconfig"
make CC=aarch64-linux-gnu-gcc -j4 wpa_supplicant wpa_cli
aarch64-linux-gnu-strip wpa_supplicant wpa_cli
cp wpa_supplicant wpa_cli "$out/"
sed '/^CFLAGS +=/d; /^LDFLAGS +=/d' .config > "$out/wpa-build.config"
cp ../COPYING "$out/wpa-LICENSE"
cp "$build/libnl-3.11.0/COPYING" "$out/libnl-LICENSE"
qemu="$(git -C "$out" rev-parse --show-toplevel)/.deps/qemu-user/root/usr/bin/qemu-aarch64-static"
"$qemu" "$out/wpa_supplicant" -v
"$qemu" "$out/wpa_cli" -v
(
    cd "$out"
    aarch64-linux-gnu-readelf -h -l wpa_supplicant wpa_cli > userspace-elf.txt
)
sha256sum "$out/wpa_supplicant" "$out/wpa_cli"
echo SOURCE_NETWORK_TOOLS_BUILT
# The small experiment helper uses the same source toolchain and QEMU tests.
cd "$(git -C "$out" rev-parse --show-toplevel)"
sh "$out/build-helper.sh"
