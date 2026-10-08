#!/bin/bash
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
out="$project/outputs/rk3568-persistent-linux-20261003"
source_archive="$project/.deps/busybox-firstboot/busybox-1.36.1.tar.bz2"
build="$out/busybox"

cd "$(dirname "$source_archive")"
sha256sum -c busybox-1.36.1.tar.bz2.sha256
if [ ! -e "$build" ]; then
    mkdir "$build"
    tar -xjf "$source_archive" -C "$build"
fi
test -f "$build/busybox-1.36.1/Makefile"
cd "$build/busybox-1.36.1"
make CROSS_COMPILE=aarch64-linux-gnu- allnoconfig > "$out/busybox-configure.log" 2>&1

python3 - <<'PY'
from pathlib import Path
import re

enabled = '''STATIC BUSYBOX LFS SHOW_USAGE FEATURE_VERBOSE_USAGE FEATURE_INSTALLER
LONG_OPTS ASH ASH_JOB_CONTROL ASH_ALIAS ASH_ECHO ASH_PRINTF ASH_TEST ASH_CMDCMD
FEATURE_SH_MATH FEATURE_SH_MATH_64 CTTYHACK SETSID CAT ECHO PRINTF TEST TEST1
TEST2 LS FEATURE_LS_FILETYPES FEATURE_LS_TIMESTAMPS
MKDIR CP RM LN MV CHMOD CHOWN TOUCH READLINK FEATURE_READLINK_FOLLOW STAT
FEATURE_STAT_FORMAT SHA256SUM FEATURE_MD5_SHA1_SUM_CHECK DF DMESG GREP SED
HEAD TAIL DD FEATURE_DD_IBS_OBS SYNC SLEEP UNAME CHROOT HEXDUMP
MOUNT FEATURE_MOUNT_FLAGS UMOUNT LOSETUP REBOOT HALT POWEROFF CPIO
GUNZIP ZCAT GZIP FEATURE_GZIP_DECOMPRESS TAR FEATURE_TAR_AUTODETECT
FEATURE_TAR_CREATE INSMOD RMMOD MODPROBE FEATURE_MODPROBE_BLACKLIST
PS FEATURE_PS_WIDE IP FEATURE_IP_ADDRESS FEATURE_IP_LINK FEATURE_IP_ROUTE
PING UDHCPC'''.split()
text = Path('.config').read_text()
for key in enabled:
    pattern = rf'^(?:# )?CONFIG_{key}(?:=.*| is not set)$'
    text, count = re.subn(pattern, f'CONFIG_{key}=y', text, flags=re.M)
    if count != 1:
        raise ValueError(f'Unknown or duplicate config: {key}')
Path('.config').write_text(text)
PY

make CROSS_COMPILE=aarch64-linux-gnu- oldconfig < /dev/null >> "$out/busybox-configure.log" 2>&1
make CROSS_COMPILE=aarch64-linux-gnu- -j4 > "$out/busybox-build.log" 2>&1
cp .config "$out/busybox.config"
cp LICENSE "$out/busybox-LICENSE"
"$project/.deps/qemu-user/root/usr/bin/qemu-aarch64-static" ./busybox --list > "$out/busybox-applets.txt"
aarch64-linux-gnu-readelf -h -l ./busybox > "$out/busybox-elf.txt"
sha256sum ./busybox
wc -c ./busybox
