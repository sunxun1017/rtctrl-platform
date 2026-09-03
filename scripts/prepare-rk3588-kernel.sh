#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 --board NAME [--build] [--jobs N]" >&2
}

board=""
build_kernel=0
jobs="${RTCTRL_BUILD_JOBS:-$(nproc)}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --board) board="${2:-}"; shift 2 ;;
    --build) build_kernel=1; shift ;;
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

for command in make "${RTCTRL_CROSS_COMPILE}gcc"; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "missing build command: ${command}" >&2
    echo "run: ./scripts/bootstrap-aarch64.sh --install" >&2
    exit 1
  fi
done

compiler_major="$(${RTCTRL_CROSS_COMPILE}gcc -dumpversion | cut -d. -f1)"
if [[ -n "${RTCTRL_KERNEL_GCC_MAJOR:-}" &&
      "${compiler_major}" != "${RTCTRL_KERNEL_GCC_MAJOR}" ]]; then
  echo "profile requires GCC ${RTCTRL_KERNEL_GCC_MAJOR}, got ${compiler_major}" >&2
  echo "run ./scripts/bootstrap-aarch64.sh --install to use the locked toolchain" >&2
  exit 1
fi

output="${repo_root}/.deps/kernel/${board}/${RTCTRL_KERNEL_COMMIT:0:12}-${RTCTRL_TOOLCHAIN_ID}"
mkdir -p -- "${output}"
make_args=(-C "${RTCTRL_KERNEL_SOURCE}" O="${output}" ARCH="${RTCTRL_ARCH}"
  CROSS_COMPILE="${RTCTRL_CROSS_COMPILE}")

make "${make_args[@]}" "${RTCTRL_KERNEL_DEFCONFIG}"
fragments=()
for fragment in ${RTCTRL_KERNEL_FRAGMENTS}; do
  fragments+=("${RTCTRL_KERNEL_SOURCE}/${fragment}")
done
fragments+=("${repo_root}/kernel/config/rt-periodic-production.cfg")
KCONFIG_CONFIG="${output}/.config" \
  "${RTCTRL_KERNEL_SOURCE}/scripts/kconfig/merge_config.sh" -m -O "${output}" \
  "${output}/.config" "${fragments[@]}"
make "${make_args[@]}" olddefconfig
"${repo_root}/scripts/check-kernel-config.sh" "${output}/.config"

if [[ "${build_kernel}" == "1" ]]; then
  make "${make_args[@]}" -j "${jobs}" Image modules "${RTCTRL_KERNEL_DTB}"
else
  make "${make_args[@]}" -j "${jobs}" prepare modules_prepare
fi

kernel_release="$(make "${make_args[@]}" -s kernelrelease)"
{
  echo "board=${RTCTRL_BOARD}"
  echo "kernel_commit=${RTCTRL_KERNEL_COMMIT}"
  echo "kernel_release=${kernel_release}"
  echo "cross_compile=${RTCTRL_CROSS_COMPILE}"
  echo "compiler=$(${RTCTRL_CROSS_COMPILE}gcc --version | head -n 1)"
  echo "dtb=${RTCTRL_KERNEL_DTB}"
  echo "full_kernel_build=${build_kernel}"
} >"${output}/rtctrl-build-manifest.txt"

echo "RK3588 kernel output: ${output}"
echo "kernel release: ${kernel_release}"
if [[ "${build_kernel}" != "1" ]]; then
  echo "modules_prepare does not produce a deployable Module.symvers; use --build before external modules"
fi
