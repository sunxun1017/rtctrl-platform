#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: cross-build-linux-userspace.sh --platform NAME
       [--sdk-root PATH] [--toolchain-bin PATH] [--sysroot PATH]
       [--target-triple TRIPLE]
       [--output PATH] [--stage PATH]
       [--jobs N] [--plan]
EOF
}

platform=""
sysroot=""
target_triple=""
toolchain_bin=""
sdk_root=""
output=""
stage=""
plan=0
jobs="${RTCTRL_BUILD_JOBS:-$(nproc)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) platform="${2:-}"; shift 2 ;;
    --sdk-root) sdk_root="${2:-}"; shift 2 ;;
    --sysroot) sysroot="${2:-}"; shift 2 ;;
    --target-triple) target_triple="${2:-}"; shift 2 ;;
    --toolchain-bin) toolchain_bin="${2:-}"; shift 2 ;;
    --output) output="${2:-}"; shift 2 ;;
    --stage) stage="${2:-}"; shift 2 ;;
    --jobs) jobs="${2:-}"; shift 2 ;;
    --plan) plan=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

if [[ -z "${platform}" || ! "${jobs}" =~ ^[1-9][0-9]*$ ]]; then
  usage
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/lib/linux-userspace-profile.sh
source "${repo_root}/scripts/lib/linux-userspace-profile.sh"
rtctrl_load_linux_userspace_profile "${repo_root}" "${platform}"

target_triple="${target_triple:-${RTCTRL_TARGET_TRIPLE_DEFAULT}}"
if [[ ! "${target_triple}" =~ ^[A-Za-z0-9_.+-]+$ ]]; then
  echo "invalid target triple: ${target_triple}" >&2
  exit 2
fi
if [[ -n "${toolchain_bin}" && "${toolchain_bin}" != /* ]]; then
  echo "--toolchain-bin must be an absolute path" >&2
  exit 2
fi
if [[ -n "${sdk_root}" && "${sdk_root}" != /* ]]; then
  echo "--sdk-root must be an absolute path" >&2
  exit 2
fi
if [[ -n "${sdk_root}" && -z "${toolchain_bin}" ]]; then
  shopt -s nullglob
  for candidate in "${sdk_root}"/buildroot/output/*/host/bin \
      "${sdk_root}"/output/*/host/bin; do
    if [[ -x "${candidate}/${target_triple}-gcc" &&
          -x "${candidate}/${target_triple}-g++" ]]; then
      toolchain_bin="${candidate}"
      break
    fi
  done
  shopt -u nullglob
  if [[ -z "${toolchain_bin}" ]]; then
    echo "no built ${target_triple} toolchain found under SDK: ${sdk_root}" >&2
    echo "materialize the SDK with ./repo.sh and build its Buildroot image first" >&2
    exit 1
  fi
fi
if [[ -z "${sysroot}" && -n "${toolchain_bin}" && -n "${RTCTRL_SYSROOT_RELATIVE:-}" ]]; then
  sysroot="${toolchain_bin}/${RTCTRL_SYSROOT_RELATIVE}"
fi
if [[ -z "${sysroot}" || "${sysroot}" != /* ]]; then
  echo "provide an absolute --sysroot, or a --toolchain-bin with a known sysroot layout" >&2
  exit 2
fi
if [[ ! -d "${sysroot}/usr/include" && ! -d "${sysroot}/include" ]]; then
  echo "invalid sysroot (missing usr/include or include): ${sysroot}" >&2
  exit 2
fi
output="${output:-${repo_root}/build/${platform}}"
stage="${stage:-${repo_root}/.deps/stage/${platform}}"

if [[ "${plan}" == "1" ]]; then
  echo "platform:      ${RTCTRL_PLATFORM}"
  echo "architecture:  ${RTCTRL_ARCH}"
  echo "target triple: ${target_triple}"
  echo "toolchain bin: ${toolchain_bin:-PATH lookup}"
  echo "sysroot:       ${sysroot}"
  echo "build output:  ${output}"
  echo "install stage: ${stage}"
  exit 0
fi

compiler_prefix="${target_triple}"
if [[ -n "${toolchain_bin}" ]]; then
  compiler_prefix="${toolchain_bin}/${target_triple}"
fi
for command in cmake ninja "${compiler_prefix}-gcc" "${compiler_prefix}-g++"; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "missing build command: ${command}" >&2
    exit 1
  fi
done

cmake -S "${repo_root}" -B "${output}" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="${repo_root}/cmake/toolchains/linux-cross.cmake" \
  -DRTCTRL_TARGET_TRIPLE="${target_triple}" \
  -DRTCTRL_TOOLCHAIN_BIN="${toolchain_bin}" \
  -DRTCTRL_SYSROOT="${sysroot}" \
  -DRTCTRL_BUILD_TESTS=OFF \
  -DRTCTRL_ENABLE_FORMAT_TARGETS=OFF
cmake --build "${output}" -j "${jobs}"
cmake --install "${output}" --prefix "${stage}"

echo "${platform} Linux userspace build complete"
echo "  build: ${output}"
echo "  stage: ${stage}"
