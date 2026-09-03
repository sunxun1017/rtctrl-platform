#!/usr/bin/env bash

rtctrl_select_cross_toolchain() {
  local repo_root="$1"
  local local_prefix="${repo_root}/.deps/toolchains/aarch64-gcc11"
  local host_tools="${repo_root}/.deps/host-tools"

  if [[ -d "${host_tools}" ]]; then
    PATH="${host_tools}:${PATH}"
  fi

  # Prefer the repository-local locked compiler so a newer system compiler
  # cannot silently change (or break) a legacy BSP build.
  if [[ -x "${local_prefix}/bin/aarch64-conda-linux-gnu-gcc" &&
          -x "${local_prefix}/bin/aarch64-conda-linux-gnu-g++" ]]; then
    PATH="${local_prefix}/bin:${PATH}"
    RTCTRL_TARGET_TRIPLE=aarch64-conda-linux-gnu
  elif command -v aarch64-linux-gnu-gcc >/dev/null 2>&1 &&
      command -v aarch64-linux-gnu-g++ >/dev/null 2>&1; then
    RTCTRL_TARGET_TRIPLE="${RTCTRL_TARGET_TRIPLE:-aarch64-linux-gnu}"
  else
    RTCTRL_TARGET_TRIPLE="${RTCTRL_TARGET_TRIPLE:-aarch64-linux-gnu}"
  fi
  RTCTRL_CROSS_COMPILE="${RTCTRL_CROSS_COMPILE:-${RTCTRL_TARGET_TRIPLE}-}"
  local compiler_version="unknown"
  if command -v "${RTCTRL_CROSS_COMPILE}gcc" >/dev/null 2>&1; then
    compiler_version="$(${RTCTRL_CROSS_COMPILE}gcc -dumpfullversion)"
  fi
  RTCTRL_TOOLCHAIN_ID="${RTCTRL_TARGET_TRIPLE}-gcc${compiler_version//./_}"
  export PATH RTCTRL_TARGET_TRIPLE RTCTRL_CROSS_COMPILE RTCTRL_TOOLCHAIN_ID
}

rtctrl_load_rk3588_profile() {
  local repo_root="$1"
  local board="$2"

  if [[ ! "${board}" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
    echo "invalid board profile name: ${board}" >&2
    return 2
  fi

  local common="${repo_root}/platforms/rk3588/common.env"
  local profile="${repo_root}/platforms/rk3588/boards/${board}/profile.env"
  if [[ ! -f "${common}" || ! -f "${profile}" ]]; then
    echo "unknown board profile: ${board}" >&2
    echo "available profiles:" >&2
    find "${repo_root}/platforms/rk3588/boards" -mindepth 2 -maxdepth 2 -name profile.env \
      -printf '  %h\n' | sed 's#.*/##' | sort >&2
    return 2
  fi

  # These files are version-controlled build data, not user input.
  # shellcheck disable=SC1090
  source "${common}"
  # shellcheck disable=SC1090
  source "${profile}"

  local required
  for required in RTCTRL_PROFILE_SCHEMA RTCTRL_SOC RTCTRL_ARCH \
      RTCTRL_TARGET_TRIPLE RTCTRL_CROSS_COMPILE RTCTRL_BOARD \
      RTCTRL_KERNEL_SUBMODULE RTCTRL_KERNEL_COMMIT RTCTRL_KERNEL_DEFCONFIG \
      RTCTRL_KERNEL_FRAGMENTS RTCTRL_KERNEL_DTB RTCTRL_KERNEL_IMAGE; do
    if [[ -z "${!required:-}" ]]; then
      echo "profile ${board} does not define ${required}" >&2
      return 2
    fi
  done
  if [[ "${RTCTRL_PROFILE_SCHEMA}" != "1" || "${RTCTRL_SOC}" != "rk3588" ||
        "${RTCTRL_ARCH}" != "arm64" || "${RTCTRL_BOARD}" != "${board}" ]]; then
    echo "profile identity mismatch for ${board}" >&2
    return 2
  fi

  RTCTRL_KERNEL_SOURCE="${repo_root}/${RTCTRL_KERNEL_SUBMODULE}"
  export RTCTRL_PROFILE_SCHEMA RTCTRL_SOC RTCTRL_ARCH RTCTRL_TARGET_TRIPLE
  export RTCTRL_CROSS_COMPILE RTCTRL_BOARD RTCTRL_KERNEL_SUBMODULE
  export RTCTRL_KERNEL_COMMIT RTCTRL_KERNEL_DEFCONFIG RTCTRL_KERNEL_FRAGMENTS
  export RTCTRL_KERNEL_DTB RTCTRL_KERNEL_IMAGE RTCTRL_KERNEL_SOURCE
  export RTCTRL_KERNEL_GCC_MAJOR
}

rtctrl_verify_kernel_source() {
  if [[ ! -f "${RTCTRL_KERNEL_SOURCE}/Makefile" ]]; then
    echo "kernel submodule is not initialized: ${RTCTRL_KERNEL_SUBMODULE}" >&2
    echo "run: git submodule update --init --recursive" >&2
    return 1
  fi
  local actual
  actual="$(git -C "${RTCTRL_KERNEL_SOURCE}" rev-parse HEAD)"
  if [[ "${actual}" != "${RTCTRL_KERNEL_COMMIT}" ]]; then
    echo "kernel commit mismatch: expected ${RTCTRL_KERNEL_COMMIT}, got ${actual}" >&2
    return 1
  fi
  local dts="${RTCTRL_KERNEL_DTB%.dtb}.dts"
  if [[ ! -f "${RTCTRL_KERNEL_SOURCE}/arch/arm64/boot/dts/${dts}" ]]; then
    echo "profile DTS source is absent: ${dts}" >&2
    return 1
  fi
}
