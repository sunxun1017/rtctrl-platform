#!/usr/bin/env bash
set -euo pipefail

install_packages=0
if [[ $# -gt 1 ]]; then
  echo "usage: $0 [--install]" >&2
  exit 2
fi
if [[ "${1:-}" == "--install" ]]; then
  install_packages=1
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--install]" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
if git -C "${repo_root}" submodule status --recursive | grep -q '^-'; then
  git -C "${repo_root}" submodule update --init --recursive
fi

host_tools="${repo_root}/.deps/host-tools"
mkdir -p -- "${host_tools}"
if ! command -v python >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  ln -sfn -- "$(command -v python3)" "${host_tools}/python"
fi
PATH="${host_tools}:${PATH}"
export PATH

host_commands=(cmake ninja make git python bc bison flex lz4 openssl pahole rsync cpio
  autoconf automake libtoolize pkg-config)
commands=("${host_commands[@]}" aarch64-linux-gnu-gcc aarch64-linux-gnu-g++)
missing=()
for command in "${commands[@]}"; do
  command -v "${command}" >/dev/null 2>&1 || missing+=("${command}")
done

if [[ "${install_packages}" == "1" ]]; then
  packages=(build-essential cmake ninja-build git gcc-aarch64-linux-gnu
    g++-aarch64-linux-gnu bc bison flex lz4 python-is-python3 libssl-dev
    libgmp-dev libmpc-dev libncurses-dev libelf-dev dwarves rsync
    cpio autoconf automake libtool pkg-config)
  if command -v apt-get >/dev/null 2>&1 && [[ "$(id -u)" == "0" ]]; then
    apt-get update
    apt-get install -y --no-install-recommends "${packages[@]}"
  elif command -v apt-get >/dev/null 2>&1 && [[ -t 0 ]] &&
      command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends "${packages[@]}"
  elif command -v conda >/dev/null 2>&1; then
    toolchain_prefix="${repo_root}/.deps/toolchains/aarch64-gcc11"
    if [[ ! -x "${toolchain_prefix}/bin/aarch64-conda-linux-gnu-gcc" ]]; then
      conda create --yes --prefix "${toolchain_prefix}" \
        --file "${repo_root}/toolchains/conda-aarch64-linux-64.lock"
    fi
    PATH="${toolchain_prefix}/bin:${PATH}"
    export PATH
  else
    echo "automatic install requires Debian/Ubuntu root/sudo or conda" >&2
    exit 1
  fi
fi

# A local, exact conda toolchain is the non-root fallback.
if [[ -x "${repo_root}/.deps/toolchains/aarch64-gcc11/bin/aarch64-conda-linux-gnu-gcc" ]]; then
  PATH="${repo_root}/.deps/toolchains/aarch64-gcc11/bin:${PATH}"
  commands=("${host_commands[@]}" aarch64-conda-linux-gnu-gcc
    aarch64-conda-linux-gnu-g++)
  export PATH
fi

missing=()
for command in "${commands[@]}"; do
  command -v "${command}" >/dev/null 2>&1 || missing+=("${command}")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "missing commands: ${missing[*]}" >&2
  echo "rerun with --install, or install the equivalent packages manually" >&2
  exit 1
fi

"${repo_root}/scripts/check-third-party.sh"
echo "AArch64 build environment is ready"
