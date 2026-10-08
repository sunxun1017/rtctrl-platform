#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Rebuild only the SHA-locked original Android boot package with AOSP functions."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType, SimpleNamespace
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BOOT = ROOT / "outputs/rk3568-backup-linux-20261003/original/boot.img"
BOOT_SIZE = 41943040
BOOT_SHA = "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28"
OFFICIAL_SIZE = 13371
OFFICIAL_SHA = "5579fb6bcb9e89e790a70fb9ccf3c00cf56e3e46aef74d84fcb0964887e5576e"
COMMIT = "99894068024224a62595e051d69e748e2499f52e"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def metadata(data):
    return {"bytes": len(data), "sha256": sha(data), "crc32": f"{zlib.crc32(data) & 0xffffffff:08x}"}


def read_locked(path, size, digest):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size != size:
                raise ValueError("Locked input must be exact-sized ordinary file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(size + 1)
            after = os.fstat(descriptor)
            if len(data) != size or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or sha(data) != digest:
                raise ValueError("Locked input SHA or identity mismatch")
            return data
        finally:
            os.close(descriptor)
    except OSError as error:
        raise ValueError("Locked input open rejected: " + str(path)) from error


def official_module(source):
    data = read_locked(source, OFFICIAL_SIZE, OFFICIAL_SHA)
    if sys.byteorder != "little":
        raise ValueError("Locked AOSP native pack format requires little-endian host")
    module = ModuleType("sha_locked_aosp_mkbootimg")
    # Execute precisely the verified bytes, without a second read or pyc lookup.
    exec(compile(data, str(source), "exec"), module.__dict__)
    return module


def auditor():
    spec = importlib.util.spec_from_file_location("boot_v2_auditor", HERE / "audit-boot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_new(path, data):
    with path.open("xb") as output:
        output.write(data)


def build(out):
    out = Path(out).absolute()
    if out != out.resolve() or not out.is_relative_to(HERE / "build"):
        raise ValueError("Need fresh non-symlink path inside own build")
    out.mkdir(parents=True, exist_ok=False)
    original = read_locked(BOOT, BOOT_SIZE, BOOT_SHA)
    module = official_module(HERE / "sources/mkbootimg.py")
    report = auditor().inspect_boot(original)
    if report["raw_bytes"] != 40019968:
        raise ValueError("Unexpected locked raw size")
    components = out / "components"
    components.mkdir()
    inputs = out / "source-inputs"
    inputs.mkdir()
    for name in ("audit-boot.py", "build-roundtrip.py", "test-boot-package.py", "PLAN.md",
                 "source-lock.json"):
        write_new(inputs / name, (HERE / name).read_bytes())
    write_new(inputs / "mkbootimg.py", read_locked(HERE / "sources/mkbootimg.py", OFFICIAL_SIZE, OFFICIAL_SHA))
    write_new(inputs / "bootimg.h", read_locked(
        HERE / "sources/bootimg.h", 9444,
        "1726e1d3182b2b415d69635f272b9af0dfc79e87b827e87459b6ef78b5dd7fad"))
    resource_source = ROOT / "third_party/linux-rk3588/scripts/resource_tool.c"
    write_new(inputs / "resource_tool.c", read_locked(
        resource_source, resource_source.stat().st_size,
        "d565a15c6c95871b762fc3599ef37bdbc4de63f6190f4f889b25ac335266b9e4"))
    for component in report["components"]:
        start, size = component["offset"], component["bytes"]
        write_new(components / component["name"], original[start:start + size])
    rsce = report["components"][2]
    resource = original[rsce["offset"]:rsce["offset"] + rsce["bytes"]]
    exports = out / "rsce"
    exports.mkdir()
    for record in report["resource"]["entries"]:
        target = exports / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        write_new(target, resource[record["offset"]:record["offset"] + record["bytes"]])
    dtbs = out / "dtb-concat"
    dtbs.mkdir()
    dtb_component = report["components"][3]
    dtb = original[dtb_component["offset"]:dtb_component["offset"] + dtb_component["bytes"]]
    for record in report["concatenated_dtbs"]:
        write_new(dtbs / f"{record['index']:02}.dtb", dtb[record["offset"]:record["offset"] + record["bytes"]])
        record["matching_rsce_paths"] = [entry["path"] for entry in report["resource"]["entries"]
                                         if entry["sha256"] == record["sha256"]]
    header = report["header"]
    with ExitStack() as stack:
        output = stack.enter_context((out / "boot-raw.img").open("xb"))
        files = {name: stack.enter_context((components / name).open("rb"))
                 for name in ("kernel", "ramdisk", "second", "dtb")}
        arguments = SimpleNamespace(
            output=output, **files, recovery_dtbo=None, header_version=2, pagesize=header["page_size"],
            base=0, kernel_offset=header["kernel_addr"], ramdisk_offset=header["ramdisk_addr"],
            second_offset=header["second_addr"], tags_offset=header["tags_addr"],
            dtb_offset=header["dtb_addr"], os_version=header["os_version"],
            os_patch_level=header["os_patch_level"], board=header["board"], cmdline=header["cmdline"])
        image_id = module.write_header(arguments)
        module.write_data(arguments, arguments.pagesize)
        output.flush()
        os.fsync(output.fileno())
    raw = (out / "boot-raw.img").read_bytes()
    if len(raw) != 40019968 or raw != original[:len(raw)]:
        raise ValueError("Official raw rebuild is not byte-identical")
    padded = raw + b"\x00" * (BOOT_SIZE - len(raw))
    if padded != original:
        raise ValueError("Padded rebuild is not byte-identical")
    write_new(out / "boot-padded.img", padded)
    rebuilt = auditor().inspect_boot(padded)
    if rebuilt["package"] != report["package"] or image_id.hex() != header["id_sha1"] + "00" * 12:
        raise ValueError("Independent post-build audit or ID failed")
    write_new(out / "audit.json", (json.dumps(report, indent=2) + "\n").encode())
    manifest = {
        "schema": 1, "mode": "original-roundtrip-only", "board_tested": False,
        "roundtrip_byte_identical": True, "official_mkbootimg_commit": COMMIT,
        "official_mkbootimg_sha256": OFFICIAL_SHA,
        "official_functions": ["write_header", "write_data"],
        "official_arguments": {key: value for key, value in vars(arguments).items()
                               if key not in ("output", "kernel", "ramdisk", "second", "dtb")},
        "original": {"path": str(BOOT.relative_to(ROOT)), **metadata(original)},
        "artifacts": {"boot-raw.img": metadata(raw), "boot-padded.img": metadata(padded)},
        "component_files": {component["name"]: metadata((components / component["name"]).read_bytes())
                            for component in report["components"]},
        "source_inputs": {path.name: metadata(path.read_bytes()) for path in sorted(inputs.iterdir())},
        "ram_boot": {
            "package_bytes": BOOT_SIZE, "package_sha256": BOOT_SHA, "package_crc32": "6e48ba06",
            "invocation": "bootm PACKAGE_ADDR",
            "command_arity": 1, "package_addr_chosen_on_board": False,
            "header_addresses_are_not_a_ram_loading_plan": True,
            "fresh_bdinfo_reserved_ranges_and_relocation_required": True,
            "flash": False, "saveenv": False, "usb_recovery_confirmed": False
        }
    }
    write_new(out / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print(json.dumps({"status": "ORIGINAL_BOOT_ROUNDTRIP_BYTE_IDENTICAL",
                      "artifacts": manifest["artifacts"], "board_tested": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()
    try:
        build(arguments.out)
    except (OSError, ValueError) as error:
        parser.exit(1, "BOOT_ROUNDTRIP_REJECTED: " + str(error) + "\n")


if __name__ == "__main__":
    main()
