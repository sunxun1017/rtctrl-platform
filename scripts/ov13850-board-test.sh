#!/bin/sh
# Run only on the identified RV1126B. IQ and harness are isolated under /tmp.
set -eu
stage=${1:?usage: sh ov13850-board-test.sh /tmp/STAGE}
case "$stage" in /tmp/ov13850-*) ;; *) echo 'stage must be /tmp/ov13850-*' >&2; exit 2;; esac
[ -d "$stage" ] && [ ! -L "$stage" ]
[ "$(uname -m)" = aarch64 ]
grep -aq 'RV1126B' /proc/device-tree/model
[ -x "$stage/ov13850-aiq-lifecycle" ]
[ -f "$stage/iq/ov13850_ATK-MCOV13850_default.json" ]
if pidof rkaiq_3A_server >/dev/null; then echo 'Existing 3A server: stop its known PID before isolated test' >&2; exit 3; fi
sensor=''; isp=''
for n in /sys/class/video4linux/v4l-subdev*/name; do
    if grep -q '^m01_b_ov13850 4-0010$' "$n"; then
        [ -z "$sensor" ] || exit 4
        sensor=/dev/$(basename "$(dirname "$n")")
    fi
done
[ -n "$sensor" ]
for m in /dev/media*; do
    media-ctl -d "$m" -p > "$stage/topology-$(basename "$m").txt"
    if grep -q 'platform:rkisp-vir1' "$stage/topology-$(basename "$m").txt" && grep -q 'rkcif-mipi-lvds2.*ENABLED' "$stage/topology-$(basename "$m").txt"; then
        [ -z "$isp" ] || exit 4
        isp=$m
    fi
done
[ -n "$isp" ]
video=$(media-ctl -d "$isp" -e rkisp_mainpath)
params=$(media-ctl -d "$isp" -e rkisp-input-params)
stats=$(media-ctl -d "$isp" -e rkisp-statistics)
printf 'sensor=%s isp=%s video=%s params=%s stats=%s\n' "$sensor" "$isp" "$video" "$params" "$stats"
v4l2-ctl -d "$video" --get-fmt-video > "$stage/format.txt"
grep -q '2112/1568' "$stage/format.txt"
grep -q "'NV12'" "$stage/format.txt"
v4l2-ctl -d "$sensor" --get-ctrl=exposure,analogue_gain,vertical_blanking > "$stage/controls-before.txt" || :
exposure=$(sed -n 's/^exposure: //p' "$stage/controls-before.txt")
gain=$(sed -n 's/^analogue_gain: //p' "$stage/controls-before.txt")
blank=$(sed -n 's/^vertical_blanking: //p' "$stage/controls-before.txt")
case "$exposure:$gain:$blank" in *[!0-9:]*|::*|:*|*:) exit 5;; esac
pid=''
cleanup() {
    if [ -n "$pid" ]; then kill -TERM "$pid" 2>/dev/null || :; wait "$pid" || :; pid=''; fi
    v4l2-ctl -d "$sensor" --set-ctrl="vertical_blanking=$blank" --set-ctrl="exposure=$exposure,analogue_gain=$gain" || :
    v4l2-ctl -d "$sensor" --get-ctrl=exposure,analogue_gain,vertical_blanking > "$stage/controls-restored.txt" || :
    grep -qx "exposure: $exposure" "$stage/controls-restored.txt"
    grep -qx "analogue_gain: $gain" "$stage/controls-restored.txt"
    grep -qx "vertical_blanking: $blank" "$stage/controls-restored.txt"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
cycles=${CYCLES:-3}
frames=${FRAMES:-180}
case "$cycles:$frames" in *[!0-9:]*|:*|*:) exit 2;; esac
[ "$cycles" -ge 1 ] && [ "$cycles" -le 100 ]
[ "$frames" -ge 30 ] && [ "$frames" -le 90000 ]
duration=$((frames / 29 + 20))
for i in $(seq 1 "$cycles"); do
    "$stage/ov13850-aiq-lifecycle" 'm01_b_ov13850 4-0010' "$stage/iq" "$duration" > "$stage/lifecycle-$i.log" 2>&1 &
    pid=$!
    ready=0
    for j in 1 2 3 4 5; do
        if grep -q '^START=0' "$stage/lifecycle-$i.log"; then ready=1; break; fi
        kill -0 "$pid"; sleep 1
    done
    [ "$ready" = 1 ]
    timeout "$duration" v4l2-ctl -d "$video" --stream-mmap=4 --stream-count="$frames" --stream-to=/dev/null --verbose > "$stage/capture-$i.log" 2>&1
    v4l2-ctl -d "$sensor" --get-ctrl=exposure,analogue_gain,vertical_blanking > "$stage/controls-after-$i.txt" || :
    kill -TERM "$pid"
    wait "$pid"
    pid=''
    grep -q '^STOP=0' "$stage/lifecycle-$i.log"
    grep -q '^DEINIT_DONE' "$stage/lifecycle-$i.log"
    echo "cycle $i OK"
done
