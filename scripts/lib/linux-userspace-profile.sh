#!/usr/bin/env bash

rtctrl_find_linux_platform_profile() {
  local repo_root="$1"
  local platform="$2"
  local matches=()
  mapfile -t matches < <(
    find "${repo_root}/platforms" -type f \
      -path "*/boards/${platform}/profile.env" -print | sort
  )
  if [[ ${#matches[@]} -ne 1 ]]; then
    echo "unknown or ambiguous Linux platform profile: ${platform}" >&2
    echo "available profiles:" >&2
    find "${repo_root}/platforms" -type f -path '*/boards/*/profile.env' \
      -printf '  %h\n' | sed 's#.*/##' | sort >&2
    return 2
  fi
  printf '%s\n' "${matches[0]}"
}

rtctrl_load_linux_userspace_profile() {
  local repo_root="$1"
  local platform="$2"

  if [[ ! "${platform}" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
    echo "invalid platform profile name: ${platform}" >&2
    return 2
  fi

  local profile
  profile="$(rtctrl_find_linux_platform_profile "${repo_root}" "${platform}")" || return
  RTCTRL_PLATFORM_DIR="$(dirname "${profile}")"
  local soc_dir
  soc_dir="$(dirname "$(dirname "${RTCTRL_PLATFORM_DIR}")")"
  local common="${soc_dir}/common.env"
  if [[ ! -f "${common}" ]]; then
    echo "profile ${platform} has no SoC common.env" >&2
    return 2
  fi

  # Profile files are version-controlled build data, not user input.
  # shellcheck disable=SC1090
  source "${common}"
  # shellcheck disable=SC1090
  source "${profile}"

  local required
  for required in RTCTRL_PROFILE_SCHEMA RTCTRL_PLATFORM RTCTRL_VENDOR RTCTRL_BOARD \
      RTCTRL_SOC RTCTRL_ARCH RTCTRL_TARGET_TRIPLE_DEFAULT RTCTRL_CMAKE_PRESET; do
    if [[ -z "${!required:-}" ]]; then
      echo "profile ${platform} does not define ${required}" >&2
      return 2
    fi
  done
  if [[ "${RTCTRL_PROFILE_SCHEMA}" != "1" || "${RTCTRL_PLATFORM}" != "${platform}" ||
        "${RTCTRL_ARCH}" != "arm64" ]]; then
    echo "profile identity mismatch for ${platform}" >&2
    return 2
  fi

  export RTCTRL_PROFILE_SCHEMA RTCTRL_PLATFORM RTCTRL_VENDOR RTCTRL_BOARD RTCTRL_SOC RTCTRL_ARCH
  export RTCTRL_TARGET_TRIPLE_DEFAULT RTCTRL_CMAKE_PRESET
  export RTCTRL_TOOLCHAIN_ROOT_NAME RTCTRL_SYSROOT_RELATIVE
  export RTCTRL_SDK_ROOT_NAME RTCTRL_PLATFORM_DIR
}
