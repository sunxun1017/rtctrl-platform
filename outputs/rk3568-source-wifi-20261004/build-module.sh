#!/bin/sh
# Same build/config/symbols as the tested RCU Image; no undefined-symbol waiver.
set -eu
export PATH="$PWD/.deps/host-tools/bin:$PATH"
kernel="$PWD/third_party/linux-rk3588"
build="$PWD/.deps/kernel/aiot-3568pq-rcu-reset"
out="$PWD/outputs/rk3568-source-wifi-20261004"
board="$PWD/platforms/rk3568/boards/aiot-3568pq"
test ! -e "$out/bcmdhd.ko"
test -z "$(git -C "$kernel" status --porcelain)"
cmp "$build/.config" "$PWD/outputs/rk3568-rcu-reset-20261004/kernel.config"
test -s "$build/vmlinux.symvers"
applied_one=0
applied_two=0
applied_three=0
applied_four=0
restore_source() {
    failed=0
    if [ "$applied_four" = 1 ]; then
        if git -C "$kernel" apply -R "$board/patches/0004-bcmdhd-out-of-tree-include.patch"; then
            applied_four=0
        else
            failed=1
        fi
    fi
    if [ "$applied_three" = 1 ]; then
        if git -C "$kernel" apply -R "$board/patches/0003-printk-rcu-flush-context.patch"; then
            applied_three=0
        else
            failed=1
        fi
    fi
    if [ "$applied_two" = 1 ]; then
        if git -C "$kernel" apply -R "$board/patches/0002-rk817-feedback-diagnostic.patch"; then
            applied_two=0
        else
            failed=1
        fi
    fi
    if [ "$applied_one" = 1 ]; then
        if git -C "$kernel" apply -R "$board/patches/0001-arm64-cache-kasan-include.patch"; then
            applied_one=0
        else
            failed=1
        fi
    fi
    return "$failed"
}
trap 'restore_source' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
git -C "$kernel" apply "$board/patches/0001-arm64-cache-kasan-include.patch"
applied_one=1
git -C "$kernel" apply "$board/patches/0002-rk817-feedback-diagnostic.patch"
applied_two=1
git -C "$kernel" apply "$board/patches/0003-printk-rcu-flush-context.patch"
applied_three=1
git -C "$kernel" apply "$board/patches/0004-bcmdhd-out-of-tree-include.patch"
applied_four=1
make -C "$kernel" O="$build" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    KBUILD_MODPOST_WARN= -j8 \
    drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/bcmdhd.ko
cp "$build/drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/bcmdhd.ko" "$out/bcmdhd.ko"
restore_source
trap - EXIT HUP INT TERM
test -z "$(git -C "$kernel" status --porcelain)"
cmp "$build/.config" "$PWD/outputs/rk3568-rcu-reset-20261004/kernel.config"
echo SAME_KERNEL_WIFI_MODULE_BUILT
