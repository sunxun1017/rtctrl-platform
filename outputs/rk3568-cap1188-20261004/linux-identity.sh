#!/bin/sh
# Only the fixed FD/FE/FF identity helper may open the SPI endpoint.
set -eu
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f62696e2f7368002f696e697400
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
test ! -e /dev/McuCom
test ! -e /sys/bus/i2c/devices/5-0062
test "$(readlink -f /sys/bus/spi/devices/spi3.0/driver)" = /sys/bus/spi/drivers/spidev
test "$(readlink -f /sys/bus/spi/devices/spi3.0/of_node)" = /sys/firmware/devicetree/base/spi@fe640000/cap1188@0
test -c /dev/spidev3.0
device_numbers=$(cat /sys/class/spidev/spidev3.0/dev)
set -- $(ls -l /dev/spidev3.0)
# This exact minimal BusyBox omits the owner/group columns (verified on board).
major_number=${3%,}
minor_number=$4
test "$major_number:$minor_number" = "$device_numbers"
test "$major_number" = 153
modules=$(cat /proc/modules)
test -z "$modules"
test ! -e /tmp/cap1188/identity-attempted
cd /tmp/cap1188
sha256sum -c upload.sha256
mkdir identity-attempted
cat /proc/bus/input/devices
cat /proc/tty/driver/serial
printf 'CAP_SPI_MESSAGES_BEFORE='; cat /sys/bus/spi/devices/spi3.0/statistics/messages; echo
printf 'CAP_SPI_ERRORS_BEFORE='; cat /sys/bus/spi/devices/spi3.0/statistics/errors; echo
printf 'CAP_SPI_TIMEOUTS_BEFORE='; cat /sys/bus/spi/devices/spi3.0/statistics/timedout; echo
if /tmp/cap1188/cap1188-inspect --inspect; then
    printf '%s\n' identity-verified > outcome
    echo CAP_SPI_IDENTITY_ACCEPTED
else
    status=$?
    printf '%s\n' identity-rejected > outcome
    echo CAP_SPI_IDENTITY_REJECTED_RC=$status
fi
printf 'CAP_SPI_MESSAGES_AFTER='; cat /sys/bus/spi/devices/spi3.0/statistics/messages; echo
printf 'CAP_SPI_ERRORS_AFTER='; cat /sys/bus/spi/devices/spi3.0/statistics/errors; echo
printf 'CAP_SPI_TIMEOUTS_AFTER='; cat /sys/bus/spi/devices/spi3.0/statistics/timedout; echo
cat /proc/tty/driver/serial
echo CAP_SPI_DIAGNOSTIC_COMPLETE_NO_INPUT_DRIVER
