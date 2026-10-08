#!/system/bin/sh
# Stage only new ordinary files; do not overwrite previous experiments.
set -eu
work=/data/local/tmp/rtctrl-rcu-reset-20261004
cache=/cache/rtctrl-rcu-reset-20261004
test "$(uname -r)" = 4.19.232
test ! -e "$cache"
test ! -L "$cache"
cd "$work"
sha256sum -c boot-inputs.sha256
sha256sum -c source-inputs.sha256
mkdir "$cache"
cp Image firstboot.dtb initramfs.cpio.gz boot-inputs.sha256 "$cache/"
cp codec-test pty-test test-source-programs.sh source-inputs.sha256 "$cache/"
chmod 600 "$cache/Image" "$cache/firstboot.dtb" "$cache/initramfs.cpio.gz" "$cache/boot-inputs.sha256"
chmod 755 "$cache/codec-test" "$cache/pty-test"
chmod 600 "$cache/test-source-programs.sh" "$cache/source-inputs.sha256"
sync
cd "$cache"
sha256sum -c boot-inputs.sha256
sha256sum -c source-inputs.sha256
echo RCU_RESET_BOOT_FILES_READY
