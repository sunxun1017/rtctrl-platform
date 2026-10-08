#!/usr/bin/env python3
"""Verify local startup backups and derive checksums for a RAM boot test."""
import hashlib
import json
from pathlib import Path
import struct
import tarfile
import zlib

ROOT = Path(__file__).resolve().parent
EXPECTED_ARCHIVE = "8e653d52d144a5a4cf8e18ca2a19211c76a3113509f958e53b259bedb4288380"
EXPECTED = {
    "boot.img": (41943040, "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28"),
    "uboot.img": (4194304, "4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e"),
    "trust.img": (4194304, "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8"),
    "dtbo.img": (4194304, "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d"),
    "vbmeta.img": (1048576, "76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752"),
}
EXPECTED_EXTRA = {
    "baseparameter.img": "b3ea054f37f20610cdb9d914287b24107d28ae0ae6e61a0134f462659506cb67",
    "misc.img": "07180514a13a608005a12f037860bdfb2a3f8359e7838c51f030ddf09fd85d84",
    "mmcblk2boot0.img": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "mmcblk2boot1.img": "bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8",
    "security.img": "08b4e750261f496f17cf1d20a54ff481f2edfb315815b8c0ce21d3094e9a5416",
    "smdt.img": "ca2a28eb7f27e22fd8bca79eff7a3b64f5012aea04f1b1801276b1be93deecf4",
    "gpt-tail.bin": "23c3c7ee71b1c03c6982510127c722bacf463e160eef1071b59a8ba976cda99c",
    "loader-head.bin": "45513eae8860c8dba56d72544b3d9fd35bac09683d716f8af561f70d57510a4e",
    "android-running.dtb": "f81341ac00389e88a91864dfc251ae0e10217135539a38b4bf434e1ae9ddef52",
    "kernel.config.gz": "709d54fd7827fae674a8f03746529150038dff7fc493f558cb1e2fc51cc75fff",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


archive = ROOT / "original.tar.gz"
require(digest(archive.read_bytes()) == EXPECTED_ARCHIVE, "Archive SHA-256 mismatch")
destination = ROOT / "original"
destination.mkdir(exist_ok=True)
with tarfile.open(archive) as bundle:
    members = bundle.getmembers()
    require(len(members) == len(EXPECTED) + 1 and {m.name for m in members} == set(EXPECTED) | {"SHA256SUMS"}, "Archive member set mismatch")
    require(all(m.isfile() and Path(m.name).name == m.name for m in members), "Unexpected archive entry")
    for member in members:
        data = bundle.extractfile(member).read()
        path = destination / member.name
        if path.exists():
            require(path.read_bytes() == data, f"Existing file differs: {path.name}")
        else:
            with path.open("xb") as stream:
                stream.write(data)

artifacts = []
for name, (size, sha) in EXPECTED.items():
    data = (destination / name).read_bytes()
    require(len(data) == size and digest(data) == sha, name)
    artifacts.append({"file": f"original/{name}", "bytes": size, "sha256": sha})

extra_seen = set()
for line in (ROOT / "extra/SHA256SUMS").read_text().splitlines():
    sha, name = line.split()
    name = name.removeprefix("./")
    require(Path(name).name == name and name in EXPECTED_EXTRA and name not in extra_seen, "Extra manifest member mismatch")
    require(sha == EXPECTED_EXTRA[name], f"Extra manifest hash mismatch: {name}")
    extra_seen.add(name)
    data = (ROOT / "extra" / name).read_bytes()
    require(digest(data) == sha, name)
    artifacts.append({"file": f"extra/{name}", "bytes": len(data), "sha256": sha})
require(extra_seen == set(EXPECTED_EXTRA), "Extra manifest is incomplete")

boot = (destination / "boot.img").read_bytes()
require(boot[:8] == b"ANDROID!", "Android boot magic mismatch")
kernel_size = struct.unpack_from("<I", boot, 8)[0]
page_size, header_version = struct.unpack_from("<II", boot, 36)
require((page_size, header_version, kernel_size) == (2048, 2, 33046536), "Android boot layout mismatch")
kernel = boot[page_size:page_size + kernel_size]
require(kernel[56:60] == b"ARMd", "ARM64 Image magic mismatch")
text_offset, image_span, flags = struct.unpack_from("<QQQ", kernel, 8)
require(digest(kernel) == "54e75d6dbb03ab96ea938eb940fe64cab91f3f81a3e43a9e98d763980dd7779d", "Kernel SHA-256 mismatch")
layout = {
    "header_version": header_version,
    "page_size": page_size,
    "kernel_file_bytes": kernel_size,
    "kernel_memory_span": image_span,
    "text_offset": text_offset,
    "image_flags": flags,
    "kernel_sha256": digest(kernel),
    "kernel_crc32": f"{zlib.crc32(kernel):08x}",
    "android_header_addresses_are_not_the_loading_plan": True,
}
dtb = (ROOT / "extra/android-running.dtb").read_bytes()
require(dtb[:4] == b"\xd0\x0d\xfe\xed", "FDT magic mismatch")
initrd = (ROOT.parent / "rk3568-boot-preparation-20260928/initramfs-verified.cpio.gz").read_bytes()
require(digest(initrd) == "2a97a6a3af2054417cd47459770629673a4655131a77c3a12dd8d30568854956", "Initrd SHA-256 mismatch")
layout["dtb_bytes"] = len(dtb)
layout["dtb_crc32"] = f"{zlib.crc32(dtb):08x}"
layout["initrd_bytes"] = len(initrd)
layout["initrd_crc32"] = f"{zlib.crc32(initrd):08x}"
(ROOT / "boot-layout.json").write_text(json.dumps(layout, indent=2) + "\n")
manifest = {
    "date": "2026-10-03",
    "startup_backup_complete": True,
    "whole_emmc_backup": False,
    "recovery_super_userdata_oempriv_backed_up": False,
    "boot_test_evidence": "boot-result.json",
    "artifacts": artifacts,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"verified_artifacts": len(artifacts), "boot_layout": layout}, indent=2))
