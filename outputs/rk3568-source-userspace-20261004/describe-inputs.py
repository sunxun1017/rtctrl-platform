#!/usr/bin/env python3
"""Describe real built inputs and generate size/CRC-checked U-Boot steps."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zlib

here = Path(__file__).resolve().parent
repo = here.parents[1]
board = repo / "platforms/rk3568/boards/aiot-3568pq"
shutil.copyfile(here / "private/dtb/rk3568-aiot-3568pq-firstboot.dtb", here / "firstboot.dtb")
artifacts = []
commands = []
checksums = ""
for name, address in (("Image", 0x400000), ("firstboot.dtb", 0x3000000), ("initramfs.cpio.gz", 0x4000000)):
    data = (here / name).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    crc = f"{zlib.crc32(data):08x}"
    artifacts.append({"file": name, "bytes": len(data), "sha256": sha, "crc32": crc,
                      "load_address": hex(address)})
    checksums += sha + "  " + name + "\n"
    commands += [{"command": f"ext4load mmc 0:c {address:x} /rtctrl-source-userspace-20261004/{name}",
                  "wait": 4, "expect": f"{len(data)} bytes read"},
                 {"command": f"crc32 {address:x} {len(data):x}", "expect": f"==> {crc}"}]
data = (here / "Image").read_bytes()
text_offset, memory_size, flags = struct.unpack_from("<QQQ", data, 8)
assert text_offset == 0 and 0x400000 + memory_size < 0x3000000
metadata = {"kernel_release": (repo / ".deps/kernel/aiot-3568pq-source-userspace-final-v2/include/config/kernel.release").read_text().strip(),
            "kernel_commit": "9f9e9d18574d0914c0d192a90c3babfe1fd63c95",
            "artifacts": artifacts, "text_offset": text_offset, "image_memory_bytes": memory_size,
            "image_flags": flags, "kernel_config_sha256": hashlib.sha256((here / "kernel.config").read_bytes()).hexdigest(),
            "patches": {name: hashlib.sha256((board / "patches" / name).read_bytes()).hexdigest()
                        for name in ("0001-arm64-cache-kasan-include.patch", "0002-rk817-feedback-diagnostic.patch")},
            "board_tested": False, "deployable": False}
(here / "boot-inputs.sha256").write_text(checksums)
(here / "kernel-artifacts.json").write_text(json.dumps(metadata, indent=2) + "\n")
commands += [{"command": "fdt addr 3000000"}, {"command": "fdt rsvmem print"},
             {"command": "fdt print /reserved-memory", "expect": "no-map"}]
(here / "load-ram.json").write_text(json.dumps(commands, indent=2) + "\n")
boot = json.loads((here.parent / "rk3568-source-kernel-20261004/boot-ram.json").read_text())
boot.insert(4, {"command": "setenv kernel_addr_r 400000"})
boot[-1] = {"command": f"booti 400000 4000000:{artifacts[2]['bytes']:x} 3000000", "wait": 40}
(here / "boot-ram.json").write_text(json.dumps(boot, indent=2) + "\n")
print(json.dumps(metadata, indent=2))
