#!/bin/sh
# Validated RV1126B face model pair; start-video.sh checks the running process.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export RKNN_INPUT_TYPE=native-fp16
export PREVIEW_JPEG_ENCODER=turbojpeg
export PREVIEW_FRAME_CONVERTER=rga
export PREVIEW_JPEG_MODE=async
exec sh "$base/start-video.sh" "$@"
