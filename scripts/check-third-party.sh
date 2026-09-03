#!/usr/bin/env bash
set -euo pipefail

readonly IGH_PATH="third_party/igh-ethercat"
readonly IGH_COMMIT="381577314d1bedc14e156512616f6dd31fb52c88"
readonly LINUX_PATH="third_party/linux-rk3588"
readonly LINUX_COMMIT="9f9e9d18574d0914c0d192a90c3babfe1fd63c95"

repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}"

if [[ ! -f "${IGH_PATH}/configure.ac" ]]; then
  echo "IgH submodule is not initialized; run:" >&2
  echo "  git submodule update --init --recursive" >&2
  exit 1
fi

actual_commit="$(git -C "${IGH_PATH}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${IGH_COMMIT}" ]]; then
  echo "IgH commit mismatch: expected ${IGH_COMMIT}, got ${actual_commit}" >&2
  exit 1
fi

if [[ -n "$(git -C "${IGH_PATH}" status --porcelain --untracked-files=all)" ]]; then
  echo "IgH submodule has local changes" >&2
  exit 1
fi

if [[ ! -f "${LINUX_PATH}/Makefile" ]]; then
  echo "RK3588 Linux submodule is not initialized; run:" >&2
  echo "  git submodule update --init --recursive" >&2
  exit 1
fi

actual_linux_commit="$(git -C "${LINUX_PATH}" rev-parse HEAD)"
if [[ "${actual_linux_commit}" != "${LINUX_COMMIT}" ]]; then
  echo "RK3588 Linux commit mismatch: expected ${LINUX_COMMIT}, got ${actual_linux_commit}" >&2
  exit 1
fi

if [[ -n "$(git -C "${LINUX_PATH}" status --porcelain --untracked-files=all)" ]]; then
  echo "RK3588 Linux submodule has local changes" >&2
  exit 1
fi

echo "third-party sources verified"
echo "  IgH EtherCAT: ${actual_commit}"
echo "  RK3588 Linux: ${actual_linux_commit}"
