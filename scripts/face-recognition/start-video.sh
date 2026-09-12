#!/bin/sh
# Run from the deployed bundle; threshold is an explicit, operator-selected value.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$base"
threshold=${1:?usage: sh start-video.sh THRESHOLD [ENROLL_NAME]}
enroll_name=${2:-}
if [ -f video.pid ]; then
    pid=$(cat video.pid)
    case "$pid" in ''|*[!0-9]*) ;; *)
        if [ "$(readlink "/proc/$pid/exe" 2>/dev/null || :)" = "$base/rtctrl_face_video" ]; then
            echo "Video is already running (PID $pid). Run stop-video.sh first." >&2
            exit 1
        fi
    esac
fi
set -- ./rtctrl_face_video --device "${CAMERA_DEVICE:-/dev/video31}" \
    --detector models/detector.rknn --recognizer models/recognizer.rknn \
    --threshold "$threshold" --gap "${FACE_GAP:-0}" \
    --bind "${PREVIEW_BIND:-0.0.0.0}" --port "${PREVIEW_PORT:-8080}" \
    --width "${PREVIEW_WIDTH:-960}" --yuv-matrix "${YUV_MATRIX:-bt601}" --yuv-range "${YUV_RANGE:-full}" \
    --input-type "${RKNN_INPUT_TYPE:-float32}" --jpeg-encoder "${PREVIEW_JPEG_ENCODER:-opencv}" \
    --frame-converter "${PREVIEW_FRAME_CONVERTER:-cpu}" \
    --jpeg-mode "${PREVIEW_JPEG_MODE:-sync}"
if [ -f gallery.json ] || [ -n "$enroll_name" ]; then
    set -- "$@" --gallery gallery.json
fi
if [ -n "$enroll_name" ]; then
    set -- "$@" --enroll-name "$enroll_name" --enroll-image "enrollment-$(date +%s).jpg"
fi
umask 077
nohup "$@" > video.log 2>&1 < /dev/null &
pid=$!
echo "$pid" > video.pid
sleep 2
if ! kill -0 "$pid" 2>/dev/null; then cat video.log >&2; exit 1; fi
echo "Video started (PID $pid), browser port ${PREVIEW_PORT:-8080}. See video.log."
