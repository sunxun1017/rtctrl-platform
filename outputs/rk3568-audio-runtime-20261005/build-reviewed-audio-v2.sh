#!/bin/sh
# Run in an already working Ubuntu terminal. No board or network operation.
set -eu

cd /home/sx/projects/rtctrl-platform

# A failed launcher does not create either output. Partial builds need review.
test ! -e outputs/rk3568-audio-runtime-20261005/build/integration-v2
test ! -L outputs/rk3568-audio-runtime-20261005/build/integration-v2
test ! -e outputs/rk3568-audio-runtime-20261005/build/integrated-codec-v2
test ! -L outputs/rk3568-audio-runtime-20261005/build/integrated-codec-v2

/usr/bin/python3 -B \
    outputs/rk3568-audio-runtime-20261005/build-audio-image-v2.py \
    --review-gate \
    outputs/rk3568-audio-runtime-20261005/build/review-gate-v3.json

/usr/bin/python3 -B \
    outputs/rk3568-audio-runtime-20261005/build-integrated-codec-v2.py

printf '%s\n' AUDIO_V2_COMPLETE_IMAGE_AND_CODEC_BUILT_NOT_BOARD_TESTED
