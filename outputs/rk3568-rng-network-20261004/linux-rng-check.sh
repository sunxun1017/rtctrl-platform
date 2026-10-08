#!/bin/sh
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /sys/bus/platform/devices/fe388000.rng/driver)" = \
    /sys/bus/platform/drivers/rockchip-rng
grep -qw rockchip /sys/class/misc/hw_random/rng_available
test "$(cat /sys/class/misc/hw_random/rng_current)" = rockchip
cat /sys/class/misc/hw_random/rng_available
cat /sys/class/misc/hw_random/rng_current
cat /proc/sys/kernel/random/entropy_avail
if test -r /sys/class/misc/hw_random/rng_selected; then
    cat /sys/class/misc/hw_random/rng_selected
fi
if test -r /sys/module/rng_core/parameters/current_quality; then
    cat /sys/module/rng_core/parameters/current_quality
fi
printf '%s  %s\n' \
    a36720bbf7f5dfee2b81e8077c95b1f8a13ef58a991436f9e1f9d4ce39e8333d \
    /tmp/entropy-check | sha256sum -c -
/tmp/entropy-check --check
echo RNG_DRIVER_AND_CRNG_CHECK_COMPLETE
