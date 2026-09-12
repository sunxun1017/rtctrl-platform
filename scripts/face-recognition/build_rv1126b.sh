#!/usr/bin/env bash
# Build static-image and video CLIs using the ATK RV1126B SDK's AArch64 dependencies.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 SDK_ROOT [BUILD_DIRECTORY]" >&2
    exit 2
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "$script_dir/../.." && pwd)
sdk_dir=$(cd -- "$1" && pwd)
build_dir=${2:-"$project_dir/build/face-rv1126b"}
toolchain_bin="$sdk_dir/prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin"
opencv_dir="$sdk_dir/external/rknpu2/examples/3rdparty/opencv/opencv-linux-aarch64/share/OpenCV"
openssl_dir="$sdk_dir/external/security/rk_tee_user/v2/host/openssl"
for required in "$toolchain_bin/aarch64-none-linux-gnu-g++" \
    "$opencv_dir/OpenCVConfig.cmake" "$openssl_dir/include/openssl/evp.h" \
    "$openssl_dir/lib/aarch64/libcrypto.a"; do
    if [[ ! -f "$required" ]]; then
        echo "Missing SDK dependency: $required" >&2
        exit 1
    fi
done
cmake -S "$project_dir" -B "$build_dir" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$project_dir/cmake/toolchains/linux-cross.cmake" \
    -DRTCTRL_TARGET_TRIPLE=aarch64-none-linux-gnu \
    -DRTCTRL_TOOLCHAIN_BIN="$toolchain_bin" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DRTCTRL_BUILD_TESTS=OFF -DRTCTRL_ENABLE_FACE_RECOGNITION=ON \
    -DRTCTRL_ENABLE_RKNN=ON -DRTCTRL_FACE_BUILD_CLI=ON -DRTCTRL_FACE_BUILD_VIDEO=ON \
    -DOpenCV_DIR="$opencv_dir" \
    -DOPENSSL_INCLUDE_DIR="$openssl_dir/include" \
    -DOPENSSL_CRYPTO_LIBRARY="$openssl_dir/lib/aarch64/libcrypto.a"
cmake --build "$build_dir" --target rtctrl_face rtctrl_face_video --parallel
printf 'Built: %s/rtctrl_face and rtctrl_face_video\n' "$build_dir"
