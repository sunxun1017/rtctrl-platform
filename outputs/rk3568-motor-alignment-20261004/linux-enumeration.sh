#!/bin/sh
# Enumerate driver metadata. Do not open a physical UART or audio capture node.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
printf '%s  %s\n' \
    514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1 \
    /bin/busybox | sha256sum -c -
printf '%s  %s\n' \
    a36720bbf7f5dfee2b81e8077c95b1f8a13ef58a991436f9e1f9d4ce39e8333d \
    /bin/entropy-check | sha256sum -c -
test "$(readlink -f /sys/bus/platform/devices/fe388000.rng/driver)" = \
    /sys/bus/platform/drivers/rockchip-rng
test "$(cat /sys/class/misc/hw_random/rng_current)" = rockchip
/bin/entropy-check --check
echo NEW_USERSPACE_AND_RNG_READY
test -c /dev/ttyS0
test "$(cat /sys/class/tty/ttyS0/dev)" = 4:64
test "$(readlink -f /sys/class/tty/ttyS0/device)" = \
    /sys/devices/platform/fdd50000.serial
test "$(readlink -f /sys/class/tty/ttyS0/device/driver)" = \
    /sys/bus/platform/drivers/dw-apb-uart
test "$(readlink -f /sys/class/tty/ttyS0/device/of_node)" = \
    /sys/firmware/devicetree/base/serial@fdd50000
test "$(cat /sys/class/tty/ttyS0/console)" = N
test -z "$(grep '^ttyS0 ' /proc/consoles || true)"
grep '^ttyFIQ0 ' /proc/consoles
cat /proc/cmdline
ls -l /dev/ttyS0
readlink -f /sys/class/tty/ttyS0/device/driver
cat /sys/class/tty/ttyS0/dev /sys/class/tty/ttyS0/console
hexdump -C /sys/class/tty/ttyS0/device/of_node/reg
echo UART_FD_SNAPSHOT_BEST_EFFORT
ls -l /proc/[0-9]*/fd/* 2>/dev/null | grep ' -> /dev/ttyS0$' || true
echo UART_COUNTERS_START
cat /proc/tty/driver/serial
sleep 10
echo UART_COUNTERS_END
cat /proc/tty/driver/serial
test ! -e /dev/McuCom
test "$(cat /sys/firmware/devicetree/base/i2c@fe5e0000/status)" = disabled
echo UART0_DRIVER_ENUMERATION_COMPLETE_NO_TTY_OPEN
test -z "$(grep ' /sys/kernel/debug ' /proc/mounts || true)"
mount -t debugfs debugfs /sys/kernel/debug
trap 'umount /sys/kernel/debug' EXIT
trap 'exit 1' HUP INT TERM
echo UART0_ACTUAL_PINMUX_OWNERS
grep -E 'pin (16|17) ' /sys/kernel/debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins
umount /sys/kernel/debug
trap - EXIT HUP INT TERM
echo USB_AUDIO_METADATA
cat /proc/asound/cards
for stream in /proc/asound/card*/stream*; do
    if test -f "$stream"; then
        cat "$stream"
    fi
done
grep -q 'Bothlent UAC Dongle' /proc/asound/cards
grep -q 'Format: S16_LE' /proc/asound/card0/stream0
grep -q 'Channels: 8' /proc/asound/card0/stream0
grep -q 'Rates: 16000' /proc/asound/card0/stream0
ls -l /dev/snd
cat /proc/bus/input/devices
echo USB_MICROPHONE_CAPABILITIES_MATCH_ANDROID
echo LINUX_ENUMERATION_COMPLETE
