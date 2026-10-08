#!/system/bin/sh
# Bind the legacy ioctl to the original Android boot Image and RK3x I2C5.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
test "$(readlink -f /sys/bus/platform/devices/fe5e0000.i2c/driver)" = /sys/bus/platform/drivers/rk3x-i2c
test "$(sha256sum /dev/block/by-name/boot)" = '0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28  /dev/block/by-name/boot'
test "$(sha256sum /data/local/tmp/rtctrl-android-identity)" = '84707cdb9370ed576f9fd7224f2d7a6f7ee165dc156bad3a755c42ecb47d44b8  /data/local/tmp/rtctrl-android-identity'
echo ORIGINAL_ANDROID_BOOT_AND_RK3X_CONTROLLER_VERIFIED
chmod 700 /data/local/tmp/rtctrl-android-identity
if /data/local/tmp/rtctrl-android-identity --android-legacy24; then
    echo ANDROID_LEGACY_IDENTITY_RC=0
else
    status=$?
    echo ANDROID_LEGACY_IDENTITY_RC=$status
fi
echo ANDROID_LEGACY_IDENTITY_DIAGNOSTIC_COMPLETE
