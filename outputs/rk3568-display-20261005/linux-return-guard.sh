#!/bin/sh
# Refuse reset until all diagnostic descriptors and persistent mounts are gone.
set -eu
mode=normal
case "$#" in
    0) ;;
    1)
        test "$1" = --stage-rejected
        mode=stage-rejected
        ;;
    *) exit 1 ;;
esac
test -f /tmp/display-stage-attempt
test ! -L /tmp/display-stage-attempt
test -f /tmp/display-return-guard.sh
test ! -L /tmp/display-return-guard.sh
test -f /tmp/display-stage.sh
test ! -L /tmp/display-stage.sh
attempt=$(cat /tmp/display-stage-attempt)
guard_fingerprint=$(sha256sum /tmp/display-return-guard.sh)
stage_fingerprint=$(sha256sum /tmp/display-stage.sh)
test "$attempt" = "display-stage-v2
$guard_fingerprint
$stage_fingerprint"
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/busybox
test "$(hexdump -v -e '1/1 "%02x"' /proc/1/cmdline)" = 2f62696e2f7368002f696e697400
test "$(sha256sum /proc/1/exe)" = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  /proc/1/exe'
modules=$(cat /proc/modules)
test -z "$modules"
loops=$(losetup -a)
test -z "$loops"
mounts=$(cat /proc/mounts)
while read -r source target kind rest; do
    case "$kind" in
        rootfs|devtmpfs|proc|sysfs|tmpfs) ;;
        *) exit 1 ;;
    esac
done <<EOF
$mounts
EOF
test ! -e /sys/class/net/wlan0
test ! -e /dev/McuCom
test ! -e /tmp/display-cache/rtctrl-display-20261005-v1
if test "$mode" = stage-rejected; then
    test ! -e /tmp/display/stage-complete
    test ! -L /tmp/display/stage-complete
    test ! -e /tmp/display/outcome
    test ! -L /tmp/display/outcome
    outcome=stage-rejected
else
    test ! -L /tmp/display/stage-complete
    test "$(cat /tmp/display/stage-complete)" = display-stage-v2-complete
    outcome=$(cat /tmp/display/outcome)
    case "$outcome" in
        interface-verified)
            test -f /tmp/display/interface-verified
            ;;
        interface-rejected) ;;
        *) exit 1 ;;
    esac
fi
check_binding() {
    device=$1
    expected=$2
    if test -L "$device/driver"; then
        driver=$(readlink -f "$device/driver") || exit 1
        test "$driver" = "$expected"
        test ! -e "$device/driver/module"
    else
        case "$outcome" in
            interface-rejected|stage-rejected) ;;
            *) exit 1 ;;
        esac
    fi
}
check_binding /sys/bus/platform/devices/display-subsystem /sys/bus/platform/drivers/rockchip-drm
check_binding /sys/bus/platform/devices/fe040000.vop /sys/bus/platform/drivers/rockchip-vop2
check_binding /sys/bus/platform/devices/fe060000.dsi /sys/bus/platform/drivers/dw-mipi-dsi-rockchip
check_binding /sys/bus/platform/devices/fe850000.phy /sys/bus/platform/drivers/inno-dsidphy
check_binding /sys/bus/platform/devices/backlight /sys/bus/platform/drivers/pwm-backlight
check_binding /sys/bus/mipi-dsi/devices/fe060000.dsi.0 /sys/bus/mipi-dsi/drivers/panel-simple-dsi
for process in /proc/[0-9]*; do
    test -d "$process" || continue
    comm=$(cat "$process/comm") || exit 1
    case "$comm" in
        display-probe|wpa_supplicant|udhcpc|tcp-probe) exit 1 ;;
    esac
    for fd in "$process"/fd/*; do
        test -L "$fd" || continue
        target=$(readlink "$fd") || exit 1
        case "$target" in
            /dev/fb*|/dev/dri/*|/dev/snd/*|/dev/spidev*|/dev/input/*|/dev/ttyS*|/dev/ttyUSB*|/dev/ttyACM*|/dev/mmcblk*|/dev/sd*|/dev/nvme*|/dev/loop*|/dev/dm-*|/dev/McuCom) exit 1 ;;
            /dev/console|/dev/ttyFIQ0)
                case "${fd##*/}" in
                    0|1|2) ;;
                    11|12|13)
                        test "$process" = /proc/1
                        test "$target" = /dev/console
                        ;;
                    *) exit 1 ;;
                esac
                test "$(readlink -f "$process/exe")" = /bin/busybox
                test "$(sha256sum "$process/exe")" = "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1  $process/exe"
                ;;
            /dev/ttyFIQ*) exit 1 ;;
        esac
    done
done
test "$(hexdump -v -e '1/1 "%02x"' /sys/module/firmware_class/parameters/path)" = 0a
printf '%s\n' "$mounts"
if test "$mode" = stage-rejected; then
    echo DISPLAY_STAGE_REJECTED_RAM_ONLY_RESET_READY
else
    echo DISPLAY_RAM_ONLY_RESET_READY
fi
