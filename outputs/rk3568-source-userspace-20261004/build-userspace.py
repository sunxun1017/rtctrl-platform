#!/usr/bin/env python3
"""Reuse verified source BusyBox/tests; no vendor modules, firmware or userspace libraries."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import zlib

here = Path(__file__).resolve().parent
old = here.parent / "rk3568-persistent-linux-20261003"
previous = here.parent / "rk3568-mcu-baseline-20261003"
bbmeta = json.loads((old / "artifacts.json").read_text())
bb = (old / "busybox/busybox-1.36.1/busybox").read_bytes()
assert hashlib.sha256(bb).hexdigest() == bbmeta["busybox_sha256"]
programs = []
for item in json.loads((previous / "result.json").read_text())["source_programs"][:2]:
    matches = list((previous / "private/source-tests").rglob(item["cmake_target"]))
    assert len(matches) == 1
    data = matches[0].read_bytes()
    assert hashlib.sha256(data).hexdigest() == item["sha256"] and len(data) == item["bytes"]
    assert data[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", data, 18)[0] == 183
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phnum = struct.unpack_from("<HH", data, 54)
    assert all(struct.unpack_from("<I", data, phoff + n * phsize)[0] != 3 for n in range(phnum))
    programs.append((item, data))
dirs = ["bin", "dev", "dev/pts", "proc", "sys", "tmp", "mnt", "mnt/cache", "mnt/root",
        "etc", "etc/rtctrl", "usr", "usr/bin", "usr/share", "usr/share/licenses", "var", "var/lib", "var/lib/rtctrl"]
base = [(name, 0o40755, b"", 0, 0) for name in dirs]
base += [("dev/console", 0o20600, b"", 5, 1), ("dev/null", 0o20666, b"", 1, 3),
         ("bin/busybox", 0o100755, bb, 0, 0)]
base += [("bin/" + name, 0o120777, b"busybox", 0, 0) for name in bbmeta["applets"]]
ram = base + [("init", 0o100755, (here / "ram-init.sh").read_bytes(), 0, 0),
              ("bin/test-userspace.sh", 0o100755, (here / "test-userspace.sh").read_bytes(), 0, 0)]
archive = bytearray()
for ino, (name, mode, payload, major, minor) in enumerate(ram + [("TRAILER!!!", 0, b"", 0, 0)], 1):
    encoded = name.encode() + b"\0"
    fields = (ino, mode, 0, 0, 1, 0, len(payload), 0, 0, major, minor, len(encoded), 0)
    archive += b"070701" + "".join(f"{value:08x}" for value in fields).encode() + encoded
    archive += bytes((-len(archive)) % 4)
    archive += payload
    archive += bytes((-len(archive)) % 4)
ramdata = gzip.compress(archive, mtime=0)
rootfiles = base + [("usr/bin/check-base.sh", 0o100755, (here / "check-base.sh").read_bytes(), 0, 0),
                    ("usr/share/licenses/BusyBox", 0o100644, (old / "busybox-LICENSE").read_bytes(), 0, 0)]
checksums = ""
for item, data in programs:
    rootfiles.append(("usr/bin/" + item["name"], 0o100755, data, 0, 0))
    checksums += item["sha256"] + "  /usr/bin/" + item["name"] + "\n"
rootfiles.append(("etc/rtctrl/source-tests.sha256", 0o100644, checksums.encode(), 0, 0))
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode="w") as bundle:
    for name, mode, payload, major, minor in rootfiles:
        info = tarfile.TarInfo(name)
        info.mode = mode & 0o7777
        kind = mode & 0o170000
        if kind == 0o040000:
            info.type = tarfile.DIRTYPE
        elif kind == 0o120000:
            info.type, info.linkname = tarfile.SYMTYPE, payload.decode()
        elif kind == 0o020000:
            info.type, info.devmajor, info.devminor = tarfile.CHRTYPE, major, minor
        else:
            info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload) if info.isreg() else None)
rootdata = gzip.compress(buffer.getvalue(), mtime=0)
for name, data in (("initramfs.cpio.gz", ramdata), ("rootfs.tar.gz", rootdata)):
    with (here / name).open("xb") as output:
        output.write(data)
metadata = {"busybox_sha256": bbmeta["busybox_sha256"],
            "source_programs": [item for item, _ in programs],
            "vendor_modules_or_libraries_included": False,
            "image_formatted_on_android": "new 64MiB ordinary file only",
            "artifacts": [{"file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                           "crc32": f"{zlib.crc32(data):08x}"}
                          for name, data in (("initramfs.cpio.gz", ramdata), ("rootfs.tar.gz", rootdata))]}
# Previous program pass flags describe the previous baseline, not this new run.
for item in metadata["source_programs"]:
    for key in ("android_passed", "independent_linux_passed", "android_opened_paths"):
        item.pop(key, None)
(here / "userspace-artifacts.json").write_text(json.dumps(metadata, indent=2) + "\n")
print(json.dumps(metadata["artifacts"], indent=2))
