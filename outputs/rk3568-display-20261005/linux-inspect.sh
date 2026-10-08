#!/bin/sh
# Read kernel interfaces at brightness zero. No display device is opened.
set -eu
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f62696e2f7368002f696e697400
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
cd /tmp/display
sha256sum -c upload.sha256
modules=$(cat /proc/modules)
test -z "$modules"
test ! -e /dev/McuCom
test ! -e /sys/class/net/wlan0
test ! -e /tmp/display/outcome
test ! -L /tmp/display/outcome
test ! -e /tmp/display/inspect
mkdir /tmp/display/inspect
echo interface-rejected > /tmp/display/outcome
failures=0
collect() {
    label=$1
    shift
    if "$@" > "/tmp/display/inspect/$label.txt" 2> "/tmp/display/inspect/$label.err"; then
        printf '%s\tOK\t0\n' "$label" >> /tmp/display/inspect/status.tsv
    else
        code=$?
        printf '%s\tFAILED\t%s\n' "$label" "$code" >> /tmp/display/inspect/status.tsv
        failures=$((failures + 1))
    fi
}
equal_value() {
    path=$1
    expected=$2
    value=$(cat "$path") || return 1
    printf '%s\n' "$value"
    test "$value" = "$expected"
}
equal_hex() {
    path=$1
    expected=$2
    value=$(hexdump -v -e '1/1 "%02x"' "$path") || return 1
    printf '%s\n' "$value"
    test "$value" = "$expected"
}
binding() {
    path=$1
    expected=$2
    value=$(readlink -f "$path/driver") || return 1
    printf '%s\n' "$value"
    test "$value" = "$expected"
    test ! -e "$path/driver/module"
}
collect uname uname -a
collect cmdline cat /proc/cmdline
collect mounts cat /proc/mounts
collect modules cat /proc/modules
collect live-fdt cat /sys/firmware/fdt
collect dmesg dmesg
collect panel-completed grep 'panel initialization sequence completed (180 commands)' /tmp/display/inspect/dmesg.txt
collect display-binding binding /sys/bus/platform/devices/display-subsystem /sys/bus/platform/drivers/rockchip-drm
collect vop-binding binding /sys/bus/platform/devices/fe040000.vop /sys/bus/platform/drivers/rockchip-vop2
collect dsi-binding binding /sys/bus/platform/devices/fe060000.dsi /sys/bus/platform/drivers/dw-mipi-dsi-rockchip
collect phy-binding binding /sys/bus/platform/devices/fe850000.phy /sys/bus/platform/drivers/inno-dsidphy
collect panel-binding binding /sys/bus/mipi-dsi/devices/fe060000.dsi.0 /sys/bus/mipi-dsi/drivers/panel-simple-dsi
collect backlight-binding binding /sys/bus/platform/devices/backlight /sys/bus/platform/drivers/pwm-backlight
collect dt-default-brightness equal_hex /sys/firmware/devicetree/base/backlight/default-brightness-level 00000000
collect dt-init-sha sha256sum /sys/firmware/devicetree/base/dsi@fe060000/panel@0/panel-init-sequence
collect dt-init-identity sh -c 'test "$(sha256sum /sys/firmware/devicetree/base/dsi@fe060000/panel@0/panel-init-sequence)" = "2457eb606192208499fb71d3e9e91cd5b6a17a2c3da9c38bc6d79cc08b81966d  /sys/firmware/devicetree/base/dsi@fe060000/panel@0/panel-init-sequence"'
for path in /sys/firmware/devicetree/base/dsi@fe060000/panel@0/dsi,flags /sys/firmware/devicetree/base/dsi@fe060000/panel@0/dsi,lanes /sys/firmware/devicetree/base/dsi@fe060000/panel@0/dsi,format /sys/firmware/devicetree/base/dsi@fe060000/panel@0/reset-gpios /sys/firmware/devicetree/base/dsi@fe060000/panel@0/enable-gpios /sys/firmware/devicetree/base/dsi@fe060000/panel@0/power-supply /sys/firmware/devicetree/base/backlight/pwms; do
    label=${path##*/}
    collect "dt-$label" hexdump -v -e '1/1 "%02x"' "$path"
done
for label in clock-frequency hactive hfront-porch hsync-len hback-porch vactive vfront-porch vsync-len vback-porch hsync-active vsync-active de-active pixelclk-active; do
    path=/sys/firmware/devicetree/base/dsi@fe060000/panel@0/display-timings/timing0/$label
    collect "timing-$label" hexdump -v -e '1/1 "%02x"' "$path"
done
collect dt-vp0-status cat /sys/firmware/devicetree/base/dsi@fe060000/ports/port@0/endpoint@0/status
collect dt-vp1-status cat /sys/firmware/devicetree/base/dsi@fe060000/ports/port@0/endpoint@1/status
collect dt-dsi-input-remote hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/dsi@fe060000/ports/port@0/endpoint@1/remote-endpoint
collect dt-vop-output-remote hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/vop@fe040000/ports/port@1/endpoint@0/remote-endpoint
collect dt-host-output-remote hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/dsi@fe060000/ports/port@1/endpoint/remote-endpoint
collect dt-panel-input-remote hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/dsi@fe060000/panel@0/port/endpoint/remote-endpoint
collect dt-dsi-input-phandle hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/dsi@fe060000/ports/port@0/endpoint@1/phandle
collect dt-vop-output-phandle hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/vop@fe040000/ports/port@1/endpoint@0/phandle
collect dt-host-output-phandle hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/dsi@fe060000/ports/port@1/endpoint/phandle
collect dt-panel-input-phandle hexdump -v -e '1/1 "%02x"' /sys/firmware/devicetree/base/dsi@fe060000/panel@0/port/endpoint/phandle
collect drm-devices ls -l /sys/class/drm
collect drm-device-target readlink -f /sys/class/drm/card0/device
collect drm-dsi-status cat /sys/class/drm/card0-DSI-1/status
collect drm-dsi-modes cat /sys/class/drm/card0-DSI-1/modes
collect fb-list cat /proc/fb
collect fb-name cat /sys/class/graphics/fb0/name
collect fb-geometry cat /sys/class/graphics/fb0/virtual_size
collect fb-bpp cat /sys/class/graphics/fb0/bits_per_pixel
collect fb-stride cat /sys/class/graphics/fb0/stride
collect backlight-brightness equal_value /sys/class/backlight/backlight/brightness 0
collect backlight-max equal_value /sys/class/backlight/backlight/max_brightness 255
collect backlight-actual equal_value /sys/class/backlight/backlight/actual_brightness 0
collect backlight-power cat /sys/class/backlight/backlight/bl_power
for device in display-subsystem fe040000.vop fe060000.dsi fe850000.phy backlight; do
    collect "runtime-$device" cat "/sys/bus/platform/devices/$device/power/runtime_status"
done
test ! -e /tmp/display-debug
mkdir /tmp/display-debug
mounted=0
release_debug() {
    if test "$mounted" = 1; then
        cd / || return 1
        umount /tmp/display-debug || return 1
        mounted=0
    fi
}
trap release_debug EXIT
trap 'exit 1' HUP INT TERM
if mount -t debugfs -o ro debugfs /tmp/display-debug; then
    mounted=1
    collect gpio cat /tmp/display-debug/gpio
    collect panel-gpio grep -E 'gpio-(5|21)[[:space:]]' /tmp/display-debug/gpio
    collect pinmux cat /tmp/display-debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins
    collect display-pinmux grep -E 'pin (5|19|21) ' /tmp/display-debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins
    collect pwm cat /tmp/display-debug/pwm
    collect clocks cat /tmp/display-debug/clk/clk_summary
    collect display-clocks grep -E 'vop|dsi|dphy|pwm' /tmp/display-debug/clk/clk_summary
    collect regulators cat /tmp/display-debug/regulator/regulator_summary
    collect drm-state cat /tmp/display-debug/dri/0/state
    collect drm-summary cat /tmp/display-debug/dri/0/summary
    cd /
    if ! release_debug; then
        echo DEBUGFS_RELEASE_FAILED
        exit 1
    fi
else
    failures=$((failures + 1))
    printf 'debugfs-mount\tFAILED\t1\n' >> /tmp/display/inspect/status.tsv
fi
trap - EXIT HUP INT TERM
cat /tmp/display/inspect/status.tsv
for file in /tmp/display/inspect/*.txt /tmp/display/inspect/*.err; do
    case "$file" in
        */live-fdt.txt) ;;
        *)
            printf 'READ_RESULT %s\n' "$file"
            cat "$file"
            ;;
    esac
done
if test "$failures" = 0; then
    touch /tmp/display/interface-verified
    echo interface-verified > /tmp/display/outcome
    echo DISPLAY_INTERFACE_METADATA_VERIFIED_AT_ZERO_BRIGHTNESS
else
    printf 'DISPLAY_INTERFACE_REJECTED failures=%s\n' "$failures"
fi
echo DISPLAY_INSPECTION_COMPLETE_NO_DEVICE_OPEN_NO_BRIGHTNESS_WRITE
test "$failures" = 0
