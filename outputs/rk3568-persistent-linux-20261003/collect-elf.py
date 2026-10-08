#!/usr/bin/env python3
"""Fetch bounded ELF metadata through ADB, rather than transferring whole libraries."""
import argparse
import base64
import json
from pathlib import Path
import shlex
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--adb", default="adb")
parser.add_argument("--target", required=True, help="verified current ADB endpoint")
args = parser.parse_args()
ADB = args.adb
TARGET = args.target

def read(path, offset, count):
    if not (0 <= offset < 100_000_000 and 0 < count <= 65536):
        raise ValueError("ELF read exceeds metadata bounds")
    command = f"dd if={shlex.quote(path)} bs=1 skip={offset} count={count} 2>/dev/null | base64"
    for attempt in range(3):
        try:
            text = subprocess.check_output([ADB, "-s", TARGET, "shell", "-T", command], timeout=30)
            data = base64.b64decode(b"".join(text.split()), validate=True)
            if len(data) != count:
                raise ValueError(f"Short ELF read: {path}")
            return data
        except (subprocess.SubprocessError, ValueError):
            if attempt == 2:
                raise
            time.sleep(0.5)

def inspect(path):
    header = read(path, 0, 64)
    if header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != 183:
        raise ValueError(f"Not little-endian ELF64 ARM64: {path}")
    elf_type = struct.unpack_from("<H", header, 16)[0]
    phoff, shoff = struct.unpack_from("<QQ", header, 32)
    phsize, phnum, shsize, shnum, shstrndx = struct.unpack_from("<HHHHH", header, 54)
    result = {"file": path, "elf_type": elf_type, "machine": "AArch64", "needed": []}
    if phnum:
        if phsize != 56 or phnum > 256:
            raise ValueError("Unexpected program header layout")
        raw = read(path, phoff, phsize * phnum)
        programs = [struct.unpack_from("<IIQQQQQQ", raw, i * phsize) for i in range(phnum)]
        dynamic = next((p for p in programs if p[0] == 2), None)
        if dynamic:
            raw = read(path, dynamic[2], dynamic[5])
            tags = []
            for off in range(0, len(raw), 16):
                tag, value = struct.unpack_from("<qQ", raw, off)
                if tag == 0:
                    break
                tags.append((tag, value))
            string_address = next(v for t, v in tags if t == 5)
            string_size = next(v for t, v in tags if t == 10)
            segment = next(p for p in programs if p[0] == 1 and p[3] <= string_address < p[3] + p[5])
            string_offset = segment[2] + string_address - segment[3]
            needed = [v for t, v in tags if t == 1]
            for offset in needed:
                value = read(path, string_offset + offset, min(256, string_size - offset))
                result["needed"].append(value.split(b"\0", 1)[0].decode())
    if elf_type == 1:
        if shsize != 64 or shnum > 1024 or shstrndx >= shnum:
            raise ValueError("Unexpected module section layout")
        raw = read(path, shoff, shnum * shsize)
        sections = [struct.unpack_from("<IIQQQQIIQQ", raw, i * shsize) for i in range(shnum)]
        names_section = sections[shstrndx]
        names = read(path, names_section[4], names_section[5])
        info = next(s for s in sections if names[s[0]:].split(b"\0", 1)[0] == b".modinfo")
        result["modinfo"] = read(path, info[4], info[5]).decode().strip("\0").split("\0")
    return result

paths = [
    "/vendor/lib64/librknnrt.so", "/system/lib64/librknn_api_android.so",
    "/vendor/lib64/librga.so", "/system/lib64/librga.so",
    "/vendor/lib64/libmpp.so", "/vendor/lib64/librkaiq.so",
    "/vendor/lib/modules/bcmdhd.ko",
]
results = []
for path in paths:
    value = inspect(path)
    results.append(value)
    print(json.dumps(value), flush=True)
(ROOT / "elf-metadata.json").write_text(json.dumps(results, indent=2) + "\n")
