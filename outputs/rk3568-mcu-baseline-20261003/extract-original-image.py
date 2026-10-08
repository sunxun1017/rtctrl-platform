#!/usr/bin/env python3
"""Extract an already backed-up original kernel for private offline analysis."""

import hashlib
import json
import struct
from pathlib import Path

repository = Path(__file__).resolve().parents[2]
backup = repository / "outputs/rk3568-backup-linux-20261003"
destination = Path(__file__).parent / "private/original-Image.bin"
layout = json.loads((backup / "boot-layout.json").read_text())

with (backup / "original/boot.img").open("rb") as stream:
    header = stream.read(64)
    if header[:8] != b"ANDROID!":
        raise SystemExit("Unexpected Android boot header")

    kernel_size = struct.unpack_from("<I", header, 8)[0]
    page_size = struct.unpack_from("<I", header, 36)[0]
    if kernel_size != layout["kernel_file_bytes"] or page_size != layout["page_size"]:
        raise SystemExit("Kernel size/page size differs from saved evidence")

    stream.seek(page_size)
    image = stream.read(kernel_size)

if len(image) != kernel_size or image[56:60] != b"ARM\x64":
    raise SystemExit("Not the expected uncompressed ARM64 Image")

digest = hashlib.sha256(image).hexdigest()
if digest != layout["kernel_sha256"]:
    raise SystemExit("Original kernel fingerprint mismatch")

with destination.open("xb") as stream:
    stream.write(image)

print(f"ORIGINAL_IMAGE_VERIFIED bytes={len(image)} sha256={digest}")
