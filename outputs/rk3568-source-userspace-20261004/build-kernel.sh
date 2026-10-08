#!/bin/sh
# Run from the repository root. Builds new output; reverses only its own patches.
set -eu
export PATH="$PWD/.deps/host-tools/bin:$PATH"
kernel="$PWD/third_party/linux-rk3588"
build="$PWD/.deps/kernel/aiot-3568pq-source-userspace-final-v2"
evidence="$PWD/outputs/rk3568-source-userspace-20261004"
board="$PWD/platforms/rk3568/boards/aiot-3568pq"
patch_one="$board/patches/0001-arm64-cache-kasan-include.patch"
patch_two="$board/patches/0002-rk817-feedback-diagnostic.patch"
test ! -e "$evidence/Image"
test ! -e "$build"

python3 scripts/prepare-linux-config.py \
    --candidate "$board/firstboot-candidate.json" \
    --output "$build"
python3 "$evidence/check-config.py" "$build/.config"
python3 "$board/build-firstboot.py" \
    --kernel "$kernel" --dtc "$PWD/.deps/kernel/aiot-3568pq-final/scripts/dtc/dtc" \
    --output "$evidence/private/dtb"

applied_one=0
applied_two=0
restore_source() {
    if [ "$applied_two" = 1 ]; then
        git -C "$kernel" apply -R "$patch_two"
    fi
    if [ "$applied_one" = 1 ]; then
        git -C "$kernel" apply -R "$patch_one"
    fi
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
python3 "$evidence/test-pmic-diagnostic.py" "$kernel/drivers/mfd/rk808.c"
make -C "$kernel" O="$build" ARCH=arm64 \
    CROSS_COMPILE=aarch64-linux-gnu- -j8 Image
cp "$build/arch/arm64/boot/Image" "$evidence/Image"
cp "$build/.config" "$evidence/kernel.config"
cp "$build/System.map" "$evidence/private/System.map"
restore_source
applied_two=0
applied_one=0
trap - EXIT HUP INT TERM
test -z "$(git -C "$kernel" status --porcelain)"
echo SOURCE_KERNEL_BUILD_COMPLETE
