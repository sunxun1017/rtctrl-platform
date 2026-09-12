#!/bin/sh
# Validated RV1126B face model pair; start-video.sh checks the running process.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export RKNN_INPUT_TYPE=native-fp16
export PREVIEW_JPEG_ENCODER=mpp
export PREVIEW_FRAME_CONVERTER=rga-direct
export CAMERA_WIDTH="${CAMERA_WIDTH:-2112}"
export CAMERA_HEIGHT="${CAMERA_HEIGHT:-1568}"
export PREVIEW_JPEG_MODE=async
exec sh "$base/start-video.sh" "$@"
