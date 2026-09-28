#!/bin/sh
# Host commands used in this investigation; run from repository root.
# Logs from earlier unsuccessful attempts are retained separately.
set -eu
export PATH="$PWD/.deps/host-tools/bin:$PATH"
K=third_party/linux-rk3588
O="$PWD/.deps/kernel/aiot-3568pq-firstboot-final-config"
E=outputs/rk3568-boot-preparation-20260928
# Initial Image attempt: kernel-image-build.log (undefined migrate_tasks).
# RT attempt: kernel-image-rt-build.log (WARN header inclusion cycle).
# Before final build, apply saved patch to the pinned clean source if needed:
# git -C "$K" apply "$PWD/$E/0001-arm64-cache-kasan-include.patch"
"$K/scripts/kconfig/merge_config.sh" -m -O "$O" "$O/.config" platforms/rk3568/boards/aiot-3568pq/firstboot.cfg
make -C "$K" O="$O" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make -C "$K" O="$O" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j8 Image
# BusyBox source fetched from official downloads, SHA checked before extraction:
# curl -fLO https://busybox.net/downloads/busybox-1.36.1.tar.bz2
# curl -fLO https://busybox.net/downloads/busybox-1.36.1.tar.bz2.sha256
# sha256sum -c busybox-1.36.1.tar.bz2.sha256
# make allnoconfig; selected minimal applets/static linkage; make oldconfig
# Exact resulting configuration: busybox.config (allnoconfig + selection).
# BusyBox does not support olddefconfig; failed attempt retained in busybox-config.log.
# make -j8 CROSS_COMPILE=aarch64-linux-gnu-
.deps/qemu-user/root/usr/bin/qemu-aarch64-static .deps/busybox-firstboot/busybox-1.36.1/busybox ash -c 'echo ARM64-shell-ok'
# Archive target must be new, so choose a fresh path when replaying:
# python3 platforms/rk3568/boards/aiot-3568pq/build-initramfs.py --busybox .deps/busybox-firstboot/busybox-1.36.1/busybox --output NEW.cpio.gz
python3 "$E/analyze-evidence.py"
gzip -dc "$E/initramfs.cpio.gz" | cpio -itv
