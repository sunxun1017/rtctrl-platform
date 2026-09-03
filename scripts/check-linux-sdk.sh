#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
usage: check-linux-sdk.sh --platform NAME --sdk-root PATH
EOF
}

platform=""
sdk_root=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) platform="${2:-}"; shift 2 ;;
        --sdk-root) sdk_root="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done

if [[ -z "${platform}" || -z "${sdk_root}" || "${sdk_root}" != /* ]]; then
    usage
    exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/lib/linux-userspace-profile.sh
source "${repo_root}/scripts/lib/linux-userspace-profile.sh"
rtctrl_load_linux_userspace_profile "${repo_root}" "${platform}"

sdk_profile="${repo_root}/platforms/${platform}/sdk.env"
if [[ ! -f "${sdk_profile}" ]]; then
    echo "platform has no SDK lock: ${platform}" >&2
    exit 2
fi
# SDK profiles are version-controlled data, not user input.
# shellcheck disable=SC1090
source "${sdk_profile}"

for required in RTCTRL_SDK_SCHEMA RTCTRL_SDK_NAME RTCTRL_SDK_RELEASE \
        RTCTRL_SDK_MANIFEST_URL RTCTRL_SDK_MANIFEST_COMMIT RTCTRL_SDK_MANIFEST_NAME \
        RTCTRL_SDK_CHECKOUT_COMMAND RTCTRL_SDK_BOARD_CONFIG RTCTRL_SDK_KERNEL_DEFCONFIG \
        RTCTRL_SDK_KERNEL_DTS RTCTRL_SDK_BUILDROOT_DEFCONFIG; do
    if [[ -z "${!required:-}" ]]; then
        echo "SDK profile does not define ${required}" >&2
        exit 2
    fi
done

if [[ "${RTCTRL_SDK_SCHEMA}" != "1" || ! -d "${sdk_root}/.repo/manifests" ]]; then
    echo "not a supported ${platform} SDK archive: ${sdk_root}" >&2
    exit 1
fi

actual_commit="$(git -C "${sdk_root}/.repo/manifests" rev-parse HEAD)"
manifest="${sdk_root}/.repo/manifests/${RTCTRL_SDK_MANIFEST_NAME}"
if [[ "${actual_commit}" != "${RTCTRL_SDK_MANIFEST_COMMIT}" || ! -f "${manifest}" ]]; then
    echo "SDK manifest does not match the platform lock" >&2
    echo "  expected: ${RTCTRL_SDK_MANIFEST_COMMIT}" >&2
    echo "  actual:   ${actual_commit}" >&2
    exit 1
fi

checkout_ready=true
for path in "${RTCTRL_SDK_BOARD_CONFIG}" "${RTCTRL_SDK_KERNEL_DEFCONFIG}" \
        "${RTCTRL_SDK_KERNEL_DTS}" "${RTCTRL_SDK_BUILDROOT_DEFCONFIG}"; do
    if [[ ! -e "${sdk_root}/${path}" ]]; then
        checkout_ready=false
    fi
done

toolchain_bin=""
shopt -s nullglob
for candidate in "${sdk_root}"/buildroot/output/*/host/bin \
        "${sdk_root}"/output/*/host/bin; do
    if [[ -x "${candidate}/${RTCTRL_TARGET_TRIPLE_DEFAULT}-gcc" &&
          -x "${candidate}/${RTCTRL_TARGET_TRIPLE_DEFAULT}-g++" ]]; then
        toolchain_bin="${candidate}"
        break
    fi
done
shopt -u nullglob

echo "platform:       ${platform}"
echo "SDK release:    ${RTCTRL_SDK_RELEASE}"
echo "manifest commit: ${actual_commit}"
echo "archive:        ready"
if [[ "${checkout_ready}" == "true" ]]; then
    echo "source checkout: ready"
else
    echo "source checkout: not materialized (run ${RTCTRL_SDK_CHECKOUT_COMMAND} in the SDK root)"
fi
if [[ -n "${toolchain_bin}" ]]; then
    echo "toolchain:      ${toolchain_bin}"
else
    echo "toolchain:      not built"
fi
