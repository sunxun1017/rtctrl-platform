#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: $0 --platform NAME [--plan] [--build-dtb] [--dtb rockchip/NAME.dtb] [--jobs N]
       $0 --platform NAME --sdk-root PATH --install-overlay [--dtb rockchip/NAME.dtb] [--plan]
       $0 --platform NAME --sdk-root PATH --build-sdk-kernel [--dtb rockchip/NAME.dtb] [--plan]
EOF
}

platform=""
plan=0
build_dtb=0
requested_dtb=""
sdk_root=""
install_overlay=0
build_sdk_kernel=0
jobs="${RTCTRL_BUILD_JOBS:-$(nproc)}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) platform="${2:-}"; shift 2 ;;
        --plan) plan=1; shift ;;
        --build-dtb) build_dtb=1; shift ;;
        --dtb) requested_dtb="${2:-}"; shift 2 ;;
        --sdk-root) sdk_root="${2:-}"; shift 2 ;;
        --install-overlay) install_overlay=1; shift ;;
        --build-sdk-kernel) build_sdk_kernel=1; install_overlay=1; shift ;;
        --jobs) jobs="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done

if [[ -z "${platform}" || ! "${platform}" =~ ^[a-z0-9][a-z0-9._-]*$ ||
      ! "${jobs}" =~ ^[1-9][0-9]*$ ||
      ( -n "${sdk_root}" && "${sdk_root}" != /* ) ||
      ( "${install_overlay}" == "1" && -z "${sdk_root}" ) ||
      ( -n "${sdk_root}" && "${install_overlay}" != "1" ) ||
      ( "${install_overlay}" == "1" && "${build_dtb}" == "1" ) ]]; then
    usage
    exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/lib/linux-userspace-profile.sh
source "${repo_root}/scripts/lib/linux-userspace-profile.sh"
rtctrl_load_linux_userspace_profile "${repo_root}" "${platform}"

if [[ -n "${requested_dtb}" ]]; then
    if [[ ! "${requested_dtb}" =~ ^rockchip/[a-zA-Z0-9._+-]+\.dtb$ ]]; then
        echo "invalid kernel DTB target: ${requested_dtb}" >&2
        exit 2
    fi
    RTCTRL_KERNEL_DTB="${requested_dtb}"
fi

for required in RTCTRL_KERNEL_UPSTREAM_URL RTCTRL_KERNEL_UPSTREAM_BRANCH \
        RTCTRL_KERNEL_SUBMODULE RTCTRL_KERNEL_COMMIT \
        RTCTRL_KERNEL_OVERLAY RTCTRL_KERNEL_DEFCONFIG RTCTRL_KERNEL_DTB; do
    if [[ -z "${!required:-}" ]]; then
        echo "kernel profile does not define ${required}" >&2
        exit 2
    fi
done

if [[ "${install_overlay}" == "1" ]]; then
    for required in RTCTRL_SDK_BOARD_CONFIG RTCTRL_SDK_KERNEL_DTS; do
        if [[ -z "${!required:-}" ]]; then
            echo "platform profile does not define ${required}" >&2
            exit 2
        fi
    done

    "${repo_root}/scripts/check-linux-sdk.sh" \
        --platform "${platform}" --sdk-root "${sdk_root}"

    sdk_kernel_relative="${RTCTRL_SDK_KERNEL_DTS%%/arch/*}"
    if [[ "${sdk_kernel_relative}" == "${RTCTRL_SDK_KERNEL_DTS}" ]]; then
        echo "cannot derive SDK kernel root from ${RTCTRL_SDK_KERNEL_DTS}" >&2
        exit 2
    fi
    sdk_kernel="${sdk_root}/${sdk_kernel_relative}"
    sdk_board_config="${sdk_root}/${RTCTRL_SDK_BOARD_CONFIG}"
    dts_name="${RTCTRL_KERNEL_DTB#rockchip/}"
    dts_name="${dts_name%.dtb}"
    custom_config_name="99_rtctrl_${platform//-/_}_defconfig"
    custom_config="$(dirname "${sdk_board_config}")/${custom_config_name}"

    if [[ ! -d "${sdk_kernel}" || ! -f "${sdk_board_config}" ||
          ! -x "${sdk_root}/build.sh" ]]; then
        echo "SDK source checkout is incomplete: ${sdk_root}" >&2
        exit 1
    fi

    echo "SDK kernel:      ${sdk_kernel}"
    echo "SDK DTS:         ${dts_name}"
    echo "SDK config:      ${custom_config}"
    if [[ "${plan}" == "1" ]]; then
        exit 0
    fi

    while IFS= read -r -d '' file; do
        relative="${file#${repo_root}/${RTCTRL_KERNEL_OVERLAY}/}"
        mkdir -p "$(dirname "${sdk_kernel}/${relative}")"
        # Do not preserve source timestamps: make must see refreshed SDK inputs.
        cp "${file}" "${sdk_kernel}/${relative}"
    done < <(find "${repo_root}/${RTCTRL_KERNEL_OVERLAY}" -type f -print0)

    config_tmp="$(mktemp "${custom_config}.tmp.XXXXXX")"
    awk -v dts="${dts_name}" '
        /^RK_KERNEL_DTS_NAME=/ { print "RK_KERNEL_DTS_NAME=\"" dts "\""; next }
        /^RK_KERNEL_MULTI_DTS=/ { print "RK_KERNEL_MULTI_DTS=\"$RK_KERNEL_DTS_NAME\""; next }
        { print }
    ' "${sdk_board_config}" > "${config_tmp}"
    mv "${config_tmp}" "${custom_config}"

    echo "installed BSP overlay and SDK config"
    if [[ "${build_sdk_kernel}" == "1" ]]; then
        # The kernel build creates its matching dtc before FIT packaging.
        sdk_build_path="${sdk_kernel}/scripts/dtc:${PATH}"
        host_tools="${repo_root}/.deps/host-tools"
        if [[ -d "${host_tools}/bin" ]]; then
            sdk_build_path="${host_tools}/bin:${sdk_build_path}"
        fi
        for command in make flex bison lz4 python; do
            if ! PATH="${sdk_build_path}" command -v "${command}" >/dev/null 2>&1; then
                echo "missing SDK kernel build command: ${command}" >&2
                echo "run ./scripts/bootstrap-aarch64.sh --install or install the equivalent package" >&2
                exit 1
            fi
        done
        if ! PATH="${sdk_build_path}" lz4 -h 2>&1 | grep -q favor-decSpeed; then
            echo "SDK kernel build requires lz4 with --favor-decSpeed support" >&2
            echo "run ./scripts/bootstrap-aarch64.sh --install or install lz4 >= 1.9.4" >&2
            exit 1
        fi
        sdk_headers=(openssl/ssl.h gmp.h mpc.h ncurses.h)
        missing_headers=()
        for header in "${sdk_headers[@]}"; do
            if ! printf '#include <%s>\n' "${header}" | \
                    cc -E -x c - >/dev/null 2>&1; then
                missing_headers+=("${header}")
            fi
        done
        if [[ ${#missing_headers[@]} -gt 0 ]]; then
            echo "missing SDK kernel build headers: ${missing_headers[*]}" >&2
            echo "run ./scripts/bootstrap-aarch64.sh --install" >&2
            exit 1
        fi

        # This SDK treats a defconfig command as an initialization-only run, so
        # selecting the config and building the kernel must be separate calls.
        (cd "${sdk_root}" && PATH="${sdk_build_path}" ./build.sh "${custom_config_name}")
        (cd "${sdk_root}" && PATH="${sdk_build_path}" ./build.sh kernel)
        sdk_boot_image="${sdk_root}/output/firmware/boot.img"
        if [[ ! -s "${sdk_boot_image}" ]]; then
            echo "SDK kernel build did not produce ${sdk_boot_image}" >&2
            exit 1
        fi
        echo "SDK boot image:  ${sdk_boot_image}"
    else
        echo "build commands:   cd ${sdk_root} && ./build.sh ${custom_config_name}"
        echo "                  cd ${sdk_root} && ./build.sh kernel"
    fi
    exit 0
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
