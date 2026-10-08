#!/bin/sh
# Inspect bindings, mux ownership and counters without opening input or SPI.
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /sys/bus/spi/devices/spi3.0/driver)" = /sys/bus/spi/drivers/spidev
test "$(readlink -f /sys/bus/spi/devices/spi3.0/of_node)" = /sys/firmware/devicetree/base/spi@fe640000/cap1188@0
test -c /dev/spidev3.0
uname -r
cat /proc/bus/input/devices
cat /proc/modules
cat /proc/tty/driver/serial
readlink -f /sys/bus/spi/devices/spi3.0/driver
cat /sys/bus/spi/devices/spi3.0/modalias
cat /sys/class/spidev/spidev3.0/dev
ls -l /dev/spidev3.0
hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/spi@fe640000/num-cs
echo
hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/spi@fe640000/cap1188@0/spi-max-frequency
echo
cat /sys/bus/spi/devices/spi3.0/statistics/messages
cat /sys/bus/spi/devices/spi3.0/statistics/errors
cat /sys/bus/spi/devices/spi3.0/statistics/timedout
mkdir /tmp/cap-debug
mount -t debugfs debugfs /tmp/cap-debug
trap 'umount /tmp/cap-debug' EXIT
trap 'exit 1' HUP INT TERM
grep -E 'pin (14|146|147|149|150|153) ' /tmp/cap-debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins
cat /tmp/cap-debug/gpio
umount /tmp/cap-debug
trap - EXIT HUP INT TERM
echo CAP_SPI_ENUMERATION_COMPLETE_NO_DEVICE_OPEN
