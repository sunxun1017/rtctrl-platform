#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
driver_dir=$(CDPATH= cd -- "$script_dir/../driver" && pwd)
kernel_dir=${1:-/lib/modules/$(uname -r)/build}
warning_level=${RTCTRL_KBUILD_WARNINGS:-1}

if [ ! -d "$kernel_dir" ] || [ ! -f "$kernel_dir/Makefile" ]; then
  printf '%s\n' "kernel build tree not found: $kernel_dir" >&2
  printf '%s\n' "usage: $0 /absolute/path/to/configured/kernel/build" >&2
  exit 2
fi

case "$kernel_dir" in
  /*) ;;
  *)
    printf '%s\n' "kernel build tree must be an absolute path" >&2
    exit 2
    ;;
esac

make -C "$kernel_dir" M="$driver_dir" W="$warning_level" modules
