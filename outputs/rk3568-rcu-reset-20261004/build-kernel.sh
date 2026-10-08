#!/bin/sh
# Run from the repository root; fresh build, three reversible local patches.
set -eu
export PATH="$PWD/.deps/host-tools/bin:$PATH"
kernel="$PWD/third_party/linux-rk3588"
build="$PWD/.deps/kernel/aiot-3568pq-rcu-reset"
evidence="$PWD/outputs/rk3568-rcu-reset-20261004"
previous="$PWD/outputs/rk3568-source-userspace-20261004"
board="$PWD/platforms/rk3568/boards/aiot-3568pq"
patch_one="$board/patches/0001-arm64-cache-kasan-include.patch"
patch_two="$board/patches/0002-rk817-feedback-diagnostic.patch"
patch_three="$board/patches/0003-printk-rcu-flush-context.patch"
test ! -e "$evidence/Image"
test ! -e "$build"
test -z "$(git -C "$kernel" status --porcelain)"

python3 scripts/prepare-linux-config.py \
    --candidate "$board/firstboot-candidate.json" \
    --output "$build"
cmp "$build/.config" "$previous/kernel.config"
python3 "$previous/check-config.py" "$build/.config"

applied_one=0
applied_two=0
applied_three=0
restore_source() {
    restore_failed=0
    if [ "$applied_three" = 1 ]; then
        if git -C "$kernel" apply -R "$patch_three"; then
            applied_three=0
        else
            echo 'Could not restore printk patch' >&2
            restore_failed=1
        fi
    fi
    if [ "$applied_two" = 1 ]; then
        if git -C "$kernel" apply -R "$patch_two"; then
            applied_two=0
        else
            echo 'Could not restore PMIC patch' >&2
            restore_failed=1
        fi
    fi
    if [ "$applied_one" = 1 ]; then
        if git -C "$kernel" apply -R "$patch_one"; then
            applied_one=0
        else
            echo 'Could not restore cache patch' >&2
            restore_failed=1
        fi
    fi
    return "$restore_failed"
}
trap 'restore_source' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

git -C "$kernel" apply --check "$patch_one"
git -C "$kernel" apply "$patch_one"
applied_one=1
git -C "$kernel" apply --check "$patch_two"
git -C "$kernel" apply "$patch_two"
applied_two=1
git -C "$kernel" apply --check "$patch_three"
git -C "$kernel" apply "$patch_three"
applied_three=1
python3 "$evidence/test-pr-flush.py" "$kernel/kernel/printk/printk.c"
python3 "$previous/test-pmic-diagnostic.py" "$kernel/drivers/mfd/rk808.c"
make -C "$kernel" O="$build" ARCH=arm64 \
    CROSS_COMPILE=aarch64-linux-gnu- -j8 Image
cp "$build/arch/arm64/boot/Image" "$evidence/Image"
cp "$build/.config" "$evidence/kernel.config"
cp "$build/System.map" "$evidence/private/System.map"
cp "$previous/firstboot.dtb" "$evidence/firstboot.dtb"
cp "$previous/initramfs.cpio.gz" "$evidence/initramfs.cpio.gz"

restore_source
trap - EXIT HUP INT TERM
test -z "$(git -C "$kernel" status --porcelain)"
echo RCU_RESET_KERNEL_BUILD_COMPLETE
