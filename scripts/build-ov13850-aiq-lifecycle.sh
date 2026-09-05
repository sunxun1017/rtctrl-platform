#!/bin/sh
set -eu
sdk=${1:?SDK root}
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
inc=$sdk/external/camera_engine_rkaiq/rkaiq/include
cc=$sdk/prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-gcc
"$cc" -g -Wall -Wextra -DISP_HW_V35 -DUSE_NEWSTRUCT=1 -I"$inc" -I"$inc/common" -I"$inc/xcore" -I"$inc/algos" -I"$inc/iq_parser_v2" -I"$inc/isp" "$repo/scripts/ov13850-aiq-lifecycle.c" -Wl,--no-as-needed -lm -ldl -o "$repo/work/ov13850-aiq-lifecycle"
