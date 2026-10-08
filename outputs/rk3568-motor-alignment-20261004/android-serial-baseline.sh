#!/system/bin/sh
# Read metadata and driver counters; never open the physical UARTs.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop sys.boot_completed)" = 1
id
uname -r
dumpsys battery
ls -l /dev/ttySMT0 /dev/ttySMT4 /dev/McuCom
cat /proc/tty/drivers
cat /proc/tty/driver/serial
for tty in ttySMT0 ttySMT4; do
    echo "TTY=$tty"
    readlink -f "/sys/class/tty/$tty/device"
    readlink -f "/sys/class/tty/$tty/device/driver"
    cat "/sys/class/tty/$tty/dev"
done
echo MCU_BINDING
readlink -f /sys/bus/i2c/devices/5-0062/driver
ls -l /sys/bus/i2c/devices/5-0062/of_node/skip-mcu
echo UART_FD_OWNERS_BEST_EFFORT
# Android toybox handles this in one process rather than one readlink per FD.
ls -l /proc/[0-9]*/fd/* 2>/dev/null |
    grep -E ' -> /dev/(ttySMT[014]|McuCom)$' || true
echo TRACE_EVENTS_AVAILABLE
grep -E '^(tty|uart|i2c|syscalls):' /sys/kernel/tracing/available_events || true
echo UART_COUNTERS_START
cat /proc/tty/driver/serial
sleep 10
echo UART_COUNTERS_END
cat /proc/tty/driver/serial
echo STARTUP_HASHES
for partition in boot uboot trust dtbo vbmeta; do
    sha256sum "/dev/block/by-name/$partition"
done
echo ANDROID_SERIAL_PASSIVE_BASELINE_COMPLETE
