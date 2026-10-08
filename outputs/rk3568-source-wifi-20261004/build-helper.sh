#!/bin/sh
set -eu
out=outputs/rk3568-source-wifi-20261004
aarch64-linux-gnu-gcc -static -O2 -Wall -Wextra -Werror \
    "$out/network-helper.c" -o "$out/network-helper"
python3 "$out/test-network-helper.py"
sha256sum "$out/network-helper"
