#!/usr/bin/env python3
"""Build separate RAM bootstrap and persistent userspace from verified static ARM64 BusyBox."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import zlib

ROOT = Path(__file__).resolve().parent
busybox = (ROOT / "busybox/busybox-1.36.1/busybox").read_bytes()
if busybox[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", busybox, 18)[0] != 183:
    raise ValueError("Need little-endian ELF64 AArch64 BusyBox")
phoff = struct.unpack_from("<Q", busybox, 32)[0]
phsize, phnum = struct.unpack_from("<HH", busybox, 54)
if any(struct.unpack_from("<I", busybox, phoff + i * phsize)[0] == 3 for i in range(phnum)):
    raise ValueError("BusyBox requires a dynamic interpreter")
applets = (ROOT / "busybox-applets.txt").read_text().splitlines()
required = {"sh", "mount", "umount", "chroot", "losetup", "sync", "reboot", "sha256sum", "stat", "cpio", "gunzip", "ip", "insmod"}
if not required <= set(applets):
    raise ValueError(f"Missing applets: {required - set(applets)}")
directories = ["bin", "dev", "proc", "sys", "tmp", "mnt", "mnt/cache", "mnt/root", "etc", "etc/rtctrl", "usr", "usr/bin", "usr/share", "usr/share/licenses", "var", "var/lib", "var/lib/rtctrl", "lib", "lib/modules", "lib/modules/4.19.232", "vendor", "vendor/etc", "vendor/etc/firmware"]
base = [(d, 0o40755, b"", 0, 0) for d in directories]
base += [("dev/console", 0o20600, b"", 5, 1), ("dev/null", 0o20666, b"", 1, 3), ("bin/busybox", 0o100755, busybox, 0, 0)]
base += [(f"bin/{name}", 0o120777, b"busybox", 0, 0) for name in applets]
ram = base + [("init", 0o100755, (ROOT / "ram-init.sh").read_bytes(), 0, 0), ("bin/open-rootfs.sh", 0o100755, (ROOT / "open-rootfs.sh").read_bytes(), 0, 0)]
archive = bytearray()
for ino, (name, mode, payload, major, minor) in enumerate(ram + [("TRAILER!!!", 0, b"", 0, 0)], 1):
    encoded = name.encode() + b"\0"
    fields = (ino, mode, 0, 0, 1, 0, len(payload), 0, 0, major, minor, len(encoded), 0)
    archive += b"070701" + "".join(f"{v:08x}" for v in fields).encode() + encoded
    archive += bytes((-len(archive)) % 4)
    archive += payload
    archive += bytes((-len(archive)) % 4)
cpio = gzip.compress(archive, mtime=0)
(ROOT / "persistent-initramfs.cpio.gz").write_bytes(cpio)

buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode="w") as bundle:
    entries = base + [("usr/bin/check-base.sh", 0o100755, (ROOT / "check-base.sh").read_bytes(), 0, 0), ("usr/share/licenses/BusyBox", 0o100644, (ROOT / "busybox-LICENSE").read_bytes(), 0, 0)]
    for name, mode, payload, major, minor in entries:
        info = tarfile.TarInfo(name)
        info.mode = mode & 0o7777
        kind = mode & 0o170000
        if kind == 0o040000:
            info.type = tarfile.DIRTYPE
        elif kind == 0o120000:
            info.type = tarfile.SYMTYPE
            info.linkname = payload.decode()
        elif kind == 0o020000:
            info.type = tarfile.CHRTYPE
            info.devmajor, info.devminor = major, minor
        else:
            info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload) if info.isreg() else None)
rootfs = gzip.compress(buffer.getvalue(), mtime=0)
(ROOT / "rootfs.tar.gz").write_bytes(rootfs)
manifest = {
    "busybox_sha256": hashlib.sha256(busybox).hexdigest(),
    "rootfs_archive_bytes": len(rootfs),
    "rootfs_archive_sha256": hashlib.sha256(rootfs).hexdigest(),
    "initramfs_bytes": len(cpio),
    "initramfs_sha256": hashlib.sha256(cpio).hexdigest(),
    "initramfs_crc32": f"{zlib.crc32(cpio):08x}",
    "applets": applets,
    "pid1_policy": "RAM supervisor; child chroot uses persistent image",
}
(ROOT / "artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({k: v for k, v in manifest.items() if k != "applets"}, indent=2))
