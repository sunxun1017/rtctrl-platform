#!/usr/bin/env bash
set -euo pipefail

readonly IGH_VERSION="1.6.12"
readonly IGH_COMMIT="381577314d1bedc14e156512616f6dd31fb52c88"
readonly IGH_REPOSITORY="https://gitlab.com/etherlab.org/ethercat.git"

if [[ $# -ne 1 ]]; then
  echo "usage: $0 OUTPUT_DIRECTORY" >&2
  exit 2
fi

output_dir="$(realpath -m -- "$1")"
if [[ "${output_dir}" == "/" || -e "${output_dir}" ]]; then
  echo "refusing output path (must not already exist): ${output_dir}" >&2
  exit 2
fi

git clone --depth 1 --branch "${IGH_VERSION}" "${IGH_REPOSITORY}" "${output_dir}"
actual_commit="$(git -C "${output_dir}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${IGH_COMMIT}" ]]; then
  echo "IgH commit mismatch: expected ${IGH_COMMIT}, got ${actual_commit}" >&2
  exit 1
fi
echo "fetched IgH EtherCAT ${IGH_VERSION} at ${actual_commit}"
