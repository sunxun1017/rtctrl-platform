#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_driver_dir=$(CDPATH= cd -- "$script_dir/../driver" && pwd)
kernel_dir=${1:-/lib/modules/$(uname -r)/build}
output_dir=${2:-}
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

if [ -n "$output_dir" ]; then
  case "$output_dir" in
    /*) ;;
    *)
      printf '%s\n' "module output directory must be an absolute path" >&2
      exit 2
      ;;
  esac
  project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
  driver_dir="$output_dir/kernel/driver"
  mkdir -p "$driver_dir" "$output_dir/include/uapi/linux"
  cp "$source_driver_dir/Makefile" "$source_driver_dir/rtctrl_mailbox.c" "$driver_dir/"
  cp "$project_root/include/uapi/linux/rtctrl_mailbox.h" "$output_dir/include/uapi/linux/"
else
  driver_dir=$source_driver_dir
fi

make -C "$kernel_dir" M="$driver_dir" W="$warning_level" modules
