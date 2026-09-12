#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$base"
[ -f video.pid ] || { echo 'No saved video PID'; exit 0; }
pid=$(cat video.pid)
case "$pid" in ''|*[!0-9]*) echo 'Invalid saved PID' >&2; exit 1;; esac
actual=$(readlink "/proc/$pid/exe" 2>/dev/null || :)
if [ "$actual" != "$base/rtctrl_face_video" ]; then
    echo 'Saved PID is no longer the video process; no signal sent.'
    exit 0
fi
kill -TERM "$pid"
for attempt in 1 2 3 4 5; do
    actual=$(readlink "/proc/$pid/exe" 2>/dev/null || :)
    [ "$actual" = "$base/rtctrl_face_video" ] || { echo 'Video stopped'; exit 0; }
    sleep 1
done
echo 'Video still stopping; inspect video.log (RKNN driver may be blocked).' >&2
exit 1
