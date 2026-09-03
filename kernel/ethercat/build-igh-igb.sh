#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 IGH_SOURCE KERNEL_BUILD OUTPUT_DIRECTORY" >&2
  echo "optional env: ARCH, CROSS_COMPILE, RTCTRL_IGH_HOST, RTCTRL_BUILD_JOBS" >&2
  exit 2
fi

source_dir="$(realpath -e -- "$1")"
kernel_build="$(realpath -e -- "$2")"
output_dir="$(realpath -m -- "$3")"

if [[ ! -f "${source_dir}/configure.ac" ||
      ! -f "${source_dir}/devices/igb/Kbuild.in" ]]; then
  echo "not an IgH source tree with the igb driver: ${source_dir}" >&2
  exit 2
fi
if [[ ! -f "${kernel_build}/Makefile" ||
      ! -f "${kernel_build}/include/generated/autoconf.h" ]]; then
  echo "kernel tree is not prepared for external modules: ${kernel_build}" >&2
  exit 2
fi
if [[ "${output_dir}" == "/" || "${output_dir}" == "${source_dir}" ||
      "${output_dir}" == "${kernel_build}" ]]; then
  echo "unsafe output directory: ${output_dir}" >&2
  exit 2
fi
mkdir -p -- "${output_dir}"

make_args=()
make_args+=("W=${RTCTRL_KERNEL_W:-1}")
if [[ -n "${ARCH:-}" ]]; then
  make_args+=("ARCH=${ARCH}")
fi
if [[ -n "${CROSS_COMPILE:-}" ]]; then
  make_args+=("CROSS_COMPILE=${CROSS_COMPILE}")
fi

kernel_source_release="$(make -s -C "${kernel_build}" "${make_args[@]}" kernelrelease)"
utsrelease_header="${kernel_build}/include/generated/utsrelease.h"
kernel_release=""
if [[ -f "${utsrelease_header}" ]]; then
  kernel_release="$(sed -n 's/^#define UTS_RELEASE "\([^"]*\)"/\1/p' "${utsrelease_header}")"
fi
if [[ -z "${kernel_release}" ]]; then
  kernel_release="${kernel_source_release}"
fi
kernel_numeric="${kernel_release%%-*}"
kernel_family="${kernel_numeric%.*}"
if [[ ! -f "${source_dir}/devices/igb/igb_main-${kernel_family}-orig.c" ]]; then
  echo "IgH does not carry an igb driver snapshot for kernel family ${kernel_family}" >&2
  echo "target kernel release: ${kernel_release}" >&2
  echo -n "available families: " >&2
  find "${source_dir}/devices/igb" -maxdepth 1 -name 'igb_main-*-orig.c' \
    -printf '%f\n' | sed -e 's/^igb_main-//' -e 's/-orig\.c$//' | sort -Vu \
    | tr '\n' ' ' >&2
  echo >&2
  exit 1
fi

if [[ ! -x "${source_dir}/configure" ]]; then
  generated_source="${output_dir}/generated-source"
  source_revision="$(git -C "${source_dir}" rev-parse HEAD 2>/dev/null || echo unversioned)"
  revision_file="${generated_source}/.rtctrl-source-revision"
  if [[ -e "${generated_source}" &&
        (! -f "${revision_file}" || "$(<"${revision_file}")" != "${source_revision}") ]]; then
    echo "generated IgH source does not match ${source_revision}: ${generated_source}" >&2
    echo "select a revision-specific empty output directory" >&2
    exit 2
  fi
  if [[ ! -d "${generated_source}" ]]; then
    mkdir -p -- "${generated_source}"
    if git -C "${source_dir}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      git -C "${source_dir}" archive HEAD | tar -x -C "${generated_source}"
    else
      cp -a -- "${source_dir}/." "${generated_source}/"
    fi
    printf '%s\n' "${source_revision}" >"${revision_file}"
  fi
  if [[ ! -x "${generated_source}/configure" ]]; then
    (cd "${generated_source}" && ./bootstrap)
  fi
  source_dir="${generated_source}"
fi

configure_args=(
  "--with-linux-dir=${kernel_build}"
  "--with-igb-kernel=${kernel_family}"
  "--enable-igb"
  "--disable-generic"
  "--enable-hrtimer"
  "--disable-eoe"
  "--disable-rt-syslog"
  "--prefix=/opt/etherlab"
  "--sysconfdir=/etc"
)
if [[ -n "${CROSS_COMPILE:-}" ]]; then
  host="${RTCTRL_IGH_HOST:-${CROSS_COMPILE%-}}"
  configure_args+=("--host=${host}")
  export CC="${CROSS_COMPILE}gcc"
  export CXX="${CROSS_COMPILE}g++"
fi

(cd "${output_dir}" && "${source_dir}/configure" "${configure_args[@]}")
jobs="${RTCTRL_BUILD_JOBS:-$(nproc)}"
make -C "${output_dir}" -j "${jobs}" "${make_args[@]}" all modules

master_module="${output_dir}/master/ec_master.ko"
igb_module="${output_dir}/devices/igb/ec_igb.ko"
if [[ ! -f "${master_module}" || ! -f "${igb_module}" ]]; then
  echo "build completed without expected ec_master/ec_igb modules" >&2
  exit 1
fi

if command -v modinfo >/dev/null 2>&1; then
  master_vermagic="$(modinfo -F vermagic "${master_module}")"
  igb_vermagic="$(modinfo -F vermagic "${igb_module}")"
  if [[ "${master_vermagic}" != "${igb_vermagic}" ]]; then
    echo "module vermagic mismatch between ec_master and ec_igb" >&2
    exit 1
  fi
  if [[ "${master_vermagic}" != "${kernel_release} "* ]]; then
    echo "module vermagic does not match target kernel ${kernel_release}" >&2
    echo "module vermagic: ${master_vermagic}" >&2
    exit 1
  fi
else
  master_vermagic="unavailable (modinfo not found)"
fi

echo "IgH native igb build complete"
echo "  kernel release: ${kernel_release}"
echo "  source release: ${kernel_source_release}"
echo "  igb snapshot:   ${kernel_family}"
echo "  master module:  ${master_module}"
echo "  igb module:     ${igb_module}"
echo "  vermagic:       ${master_vermagic}"
echo "modules were built only; nothing was installed or loaded"
