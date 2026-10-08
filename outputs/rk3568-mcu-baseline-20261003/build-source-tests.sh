#!/bin/sh
# Build existing source tests; physical UARTs are never opened by these tests.
set -eu

repository=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
output_dir=$repository/outputs/rk3568-mcu-baseline-20261003/private/source-tests

if [ -e "$output_dir" ]; then
    echo "Refusing existing build directory: $output_dir" >&2
    exit 1
fi

cmake -S "$repository" -B "$output_dir" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$repository/cmake/toolchains/linux-cross.cmake" \
    -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
    -DRTCTRL_TARGET_TRIPLE=aarch64-linux-gnu \
    -DCMAKE_EXE_LINKER_FLAGS=-static \
    -DRTCTRL_BUILD_TESTS=ON \
    -DRTCTRL_ENABLE_SERIAL=ON \
    -DRTCTRL_ENABLE_RKNN=OFF \
    -DRTCTRL_ENABLE_FACE_RECOGNITION=OFF \
    -DRTCTRL_ENABLE_FORMAT_TARGETS=OFF

cmake --build "$output_dir" --target \
    rtctrl_patchx_codec_test rtctrl_patchx_pty_test -j2

for target in rtctrl_patchx_codec_test rtctrl_patchx_pty_test; do
    executable=$(find "$output_dir" -type f -name "$target" -print)

    if [ -z "$executable" ]; then
        echo "Missing executable: $target" >&2
        exit 1
    fi

    aarch64-linux-gnu-readelf -h -l -d "$executable" \
        > "$output_dir/$target.elf.txt"

    if grep -Eq 'INTERP|NEEDED' "$output_dir/$target.elf.txt"; then
        echo "Unexpected dynamic runtime dependency: $target" >&2
        exit 1
    fi

    sha256sum "$executable"
done
