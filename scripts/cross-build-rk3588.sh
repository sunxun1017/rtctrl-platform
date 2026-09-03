#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 --board NAME [--plan] [--userspace-only] [--skip-ethercat] [--jobs N]" >&2
}

board=""
plan=0
userspace_only=0
skip_ethercat=0
jobs="${RTCTRL_BUILD_JOBS:-$(nproc)}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --board) board="${2:-}"; shift 2 ;;
    --plan) plan=1; shift ;;
    --userspace-only) userspace_only=1; shift ;;
    --skip-ethercat) skip_ethercat=1; shift ;;
    --jobs) jobs="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done
if [[ -z "${board}" || ! "${jobs}" =~ ^[1-9][0-9]*$ ]]; then
  usage
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/lib/rk3588-profile.sh
source "${repo_root}/scripts/lib/rk3588-profile.sh"
rtctrl_select_cross_toolchain "${repo_root}"
rtctrl_load_rk3588_profile "${repo_root}" "${board}"
rtctrl_verify_kernel_source

kernel_output="${repo_root}/.deps/kernel/${board}/${RTCTRL_KERNEL_COMMIT:0:12}-${RTCTRL_TOOLCHAIN_ID}"
build_identity="${RTCTRL_KERNEL_COMMIT:0:12}-${RTCTRL_TOOLCHAIN_ID}"
igh_output="${repo_root}/.deps/igh/${board}/${build_identity}"
igh_stage="${repo_root}/.deps/stage/${board}/${build_identity}/etherlab"
user_output="${repo_root}/build/aarch64-${board}-${RTCTRL_TOOLCHAIN_ID}"

if [[ "${plan}" == "1" ]]; then
  echo "board:          ${RTCTRL_BOARD}"
  echo "kernel source: ${RTCTRL_KERNEL_SUBMODULE}@${RTCTRL_KERNEL_COMMIT}"
  echo "kernel DTB:    ${RTCTRL_KERNEL_DTB}"
  echo "kernel output: ${kernel_output}"
  echo "IgH output:    ${igh_output}"
  echo "user output:   ${user_output}"
  echo "userspace only:${userspace_only}"
  echo "skip EtherCAT: ${skip_ethercat}"
  exit 0
fi

for command in cmake ninja "${RTCTRL_CROSS_COMPILE}gcc" "${RTCTRL_CROSS_COMPILE}g++"; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "missing build command: ${command}" >&2
    echo "run: ./scripts/bootstrap-aarch64.sh --install" >&2
    exit 1
  fi
done

cmake_args=(-S "${repo_root}" -B "${user_output}" -G Ninja
  -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_TOOLCHAIN_FILE="${repo_root}/cmake/toolchains/linux-cross.cmake"
  -DRTCTRL_TARGET_TRIPLE="${RTCTRL_TARGET_TRIPLE}"
  -DRTCTRL_BUILD_TESTS=OFF)
if [[ -n "${RTCTRL_SYSROOT:-}" ]]; then
  cmake_args+=("-DRTCTRL_SYSROOT=${RTCTRL_SYSROOT}")
fi

if [[ "${userspace_only}" != "1" ]]; then
  "${repo_root}/scripts/prepare-rk3588-kernel.sh" --board "${board}" --build --jobs "${jobs}"
  ARCH="${RTCTRL_ARCH}" CROSS_COMPILE="${RTCTRL_CROSS_COMPILE}" \
    "${repo_root}/kernel/scripts/build-module.sh" "${kernel_output}" \
    "${repo_root}/.deps/mailbox/${board}/${build_identity}"

  if [[ "${skip_ethercat}" != "1" ]]; then
    ARCH="${RTCTRL_ARCH}" CROSS_COMPILE="${RTCTRL_CROSS_COMPILE}" \
      RTCTRL_IGH_HOST="${RTCTRL_TARGET_TRIPLE}" RTCTRL_BUILD_JOBS="${jobs}" \
      "${repo_root}/kernel/ethercat/build-igh-igb.sh" \
      "${repo_root}/third_party/igh-ethercat" "${kernel_output}" "${igh_output}"
    mkdir -p -- "${igh_stage}/include" "${igh_stage}/lib"
    cp -a -- "${repo_root}/third_party/igh-ethercat/include/ecrt.h" \
      "${igh_stage}/include/"
    cp -a -- "${igh_output}/lib/.libs/libethercat.so"* "${igh_stage}/lib/"
    cmake_args+=( -DRTCTRL_ENABLE_IGH_ETHERCAT=ON
      "-DRTCTRL_IGH_ROOT=${igh_stage}" )
  fi
fi

cmake "${cmake_args[@]}"
cmake --build "${user_output}" -j "${jobs}"

echo "RK3588 cross build complete"
echo "  board: ${board}"
echo "  user space: ${user_output}"
if [[ "${userspace_only}" != "1" ]]; then
  echo "  kernel: ${kernel_output}/${RTCTRL_KERNEL_IMAGE}"
  echo "  DTB: ${kernel_output}/arch/arm64/boot/dts/${RTCTRL_KERNEL_DTB}"
fi
