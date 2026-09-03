#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: $0 --platform NAME [--plan] [--build-dtb] [--jobs N]" >&2
}

platform=""
plan=0
build_dtb=0
jobs="${RTCTRL_BUILD_JOBS:-$(nproc)}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) platform="${2:-}"; shift 2 ;;
        --plan) plan=1; shift ;;
        --build-dtb) build_dtb=1; shift ;;
        --jobs) jobs="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done

if [[ -z "${platform}" || ! "${platform}" =~ ^[a-z0-9][a-z0-9._-]*$ ||
      ! "${jobs}" =~ ^[1-9][0-9]*$ ]]; then
    usage
    exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
profile="${repo_root}/platforms/${platform}/kernel.env"
if [[ ! -f "${profile}" ]]; then
    echo "platform has no public kernel profile: ${platform}" >&2
    exit 2
fi
# Kernel profiles are version-controlled build data, not user input.
# shellcheck disable=SC1090
source "${profile}"

for required in RTCTRL_KERNEL_PROFILE_SCHEMA RTCTRL_KERNEL_UPSTREAM_URL \
        RTCTRL_KERNEL_UPSTREAM_BRANCH RTCTRL_KERNEL_SUBMODULE RTCTRL_KERNEL_COMMIT \
        RTCTRL_KERNEL_OVERLAY RTCTRL_KERNEL_DEFCONFIG RTCTRL_KERNEL_DTB; do
    if [[ -z "${!required:-}" ]]; then
        echo "kernel profile does not define ${required}" >&2
        exit 2
    fi
done
if [[ "${RTCTRL_KERNEL_PROFILE_SCHEMA}" != "1" ]]; then
    echo "unsupported kernel profile schema" >&2
    exit 2
fi

kernel_source="${repo_root}/${RTCTRL_KERNEL_SUBMODULE}"
overlay="${repo_root}/${RTCTRL_KERNEL_OVERLAY}"
if [[ ! -f "${kernel_source}/Makefile" ]]; then
    echo "kernel submodule is not initialized: ${RTCTRL_KERNEL_SUBMODULE}" >&2
    echo "run: git submodule update --init --depth 1 ${RTCTRL_KERNEL_SUBMODULE}" >&2
    exit 1
fi
actual_commit="$(git -C "${kernel_source}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${RTCTRL_KERNEL_COMMIT}" ]]; then
    echo "kernel commit mismatch: expected ${RTCTRL_KERNEL_COMMIT}, got ${actual_commit}" >&2
    exit 1
fi
if [[ ! -d "${overlay}" ]]; then
    echo "missing board overlay: ${RTCTRL_KERNEL_OVERLAY}" >&2
    exit 1
fi

overlay_id="$(
    cd "${overlay}"
    find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1
)"
prepared="${repo_root}/.deps/kernel-source/${platform}/${RTCTRL_KERNEL_COMMIT:0:12}-${overlay_id:0:12}"
kernel_output="${repo_root}/.deps/kernel-build/${platform}/${RTCTRL_KERNEL_COMMIT:0:12}-${overlay_id:0:12}"

if [[ "${plan}" == "1" ]]; then
    echo "platform:        ${platform}"
    echo "public kernel:   ${RTCTRL_KERNEL_UPSTREAM_URL}"
    echo "upstream branch: ${RTCTRL_KERNEL_UPSTREAM_BRANCH}"
    echo "kernel commit:   ${RTCTRL_KERNEL_COMMIT}"
    echo "board overlay:   ${RTCTRL_KERNEL_OVERLAY}@${overlay_id}"
    echo "prepared source: ${prepared}"
    echo "kernel output:   ${kernel_output}"
    echo "kernel config:   ${RTCTRL_KERNEL_DEFCONFIG}"
    echo "kernel DTB:      ${RTCTRL_KERNEL_DTB}"
    exit 0
fi

if [[ ! -d "${prepared}/.git" ]]; then
    mkdir -p "$(dirname "${prepared}")"
    git clone --quiet --shared --no-checkout "${kernel_source}" "${prepared}"
    git -C "${prepared}" checkout --quiet --detach "${RTCTRL_KERNEL_COMMIT}"
fi
if [[ "$(git -C "${prepared}" rev-parse HEAD)" != "${RTCTRL_KERNEL_COMMIT}" ]]; then
    echo "prepared kernel source has an unexpected commit: ${prepared}" >&2
    exit 1
fi

while IFS= read -r -d '' file; do
    relative="${file#${overlay}/}"
    mkdir -p "$(dirname "${prepared}/${relative}")"
    cp -a "${file}" "${prepared}/${relative}"
done < <(find "${overlay}" -type f -print0)

if [[ ! -f "${prepared}/arch/arm64/configs/${RTCTRL_KERNEL_DEFCONFIG}" ||
      ! -f "${prepared}/arch/arm64/boot/dts/${RTCTRL_KERNEL_DTB%.dtb}.dts" ]]; then
    echo "prepared kernel is missing the selected config or DTS" >&2
    exit 1
fi

echo "prepared kernel source: ${prepared}"
echo "upstream: ${RTCTRL_KERNEL_COMMIT}"
echo "overlay:  ${overlay_id}"

if [[ "${build_dtb}" == "1" ]]; then
    host_tools="${repo_root}/.deps/host-tools"
    if [[ -d "${host_tools}/bin" ]]; then
        PATH="${host_tools}/bin:${PATH}"
    fi
    cross_compile="${RTCTRL_CROSS_COMPILE:-aarch64-linux-gnu-}"
    for command in make flex bison "${cross_compile}gcc"; do
        if ! command -v "${command}" >/dev/null 2>&1; then
            echo "missing kernel build command: ${command}" >&2
            echo "run ./scripts/bootstrap-aarch64.sh --install or install the equivalent package" >&2
            exit 1
        fi
    done
    make_args=(-C "${prepared}" O="${kernel_output}" ARCH=arm64
        CROSS_COMPILE="${cross_compile}")
    make "${make_args[@]}" "${RTCTRL_KERNEL_DEFCONFIG}"
    make "${make_args[@]}" -j "${jobs}" "${RTCTRL_KERNEL_DTB}"
    dtb="${kernel_output}/arch/arm64/boot/dts/${RTCTRL_KERNEL_DTB}"
    if [[ ! -s "${dtb}" ]]; then
        echo "kernel build did not produce the selected DTB: ${dtb}" >&2
        exit 1
    fi
    echo "kernel DTB: ${dtb}"
fi
