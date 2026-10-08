#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded offline Android boot v2, RSCE and concatenated FDT inspection."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import zlib

HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def block(data, offset, size, context):
    require(offset >= 0 and size >= 0 and offset <= len(data) and size <= len(data) - offset,
            context + " outside input")
    return data[offset:offset + size]


def zero(data, context):
    require(not any(data), context + " must be zero")


def ascii_string(data, context):
    end = data.find(b"\x00")
    require(end >= 0, context + " missing terminator")
    zero(data[end + 1:], context + " padding")
    try:
        value = data[:end].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError(context + " non-ASCII") from error
    require(all(32 <= ord(character) < 127 for character in value), context + " invalid ASCII")
    return value


def hashes(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "sha1": hashlib.sha1(data).hexdigest(), "crc32": f"{zlib.crc32(data) & 0xffffffff:08x}"}


def string_list(data, context):
    require(bool(data) and data[-1:] == b"\x00", context + " invalid string list")
    try:
        values = data[:-1].decode("ascii").split("\x00")
    except UnicodeDecodeError as error:
        raise ValueError(context + " non-ASCII string") from error
    require(all(values), context + " empty string")
    return values


def inspect_fdt(data):
    require(len(data) >= 40, "FDT truncated header")
    magic, total, off_struct, off_strings, off_reserve, version, compatible_version, cpu, strings_size, struct_size = struct.unpack_from(">10I", data)
    require(magic == 0xd00dfeed and total == len(data), "FDT magic or totalsize")
    require(version == 17 and compatible_version == 16, "FDT unsupported version")
    require(off_struct >= 40 and off_struct % 4 == 0 and off_strings >= 40 and
            off_reserve >= 40 and off_reserve % 8 == 0, "FDT offsets or alignment")
    structure = block(data, off_struct, struct_size, "FDT structure")
    strings = block(data, off_strings, strings_size, "FDT strings")
    reserve = off_reserve
    reservations = []
    while True:
        pair = block(data, reserve, 16, "FDT reserve map")
        address, size = struct.unpack(">QQ", pair)
        reserve += 16
        if address == size == 0:
            break
        require(len(reservations) < 256, "FDT reserve map count")
        reservations.append({"address": address, "bytes": size})
    ranges = sorted([(0, 40), (off_reserve, reserve),
                     (off_struct, off_struct + struct_size), (off_strings, off_strings + strings_size)])
    require(all(left[1] <= right[0] for left, right in zip(ranges, ranges[1:])), "FDT sections overlap")
    position = 0
    stack = []
    properties_seen = set()
    nodes_seen = set()
    root_properties = {}
    selected = {}
    node_count = property_count = 0
    ended = False
    while position < len(structure):
        token = struct.unpack(">I", block(structure, position, 4, "FDT token"))[0]
        position += 4
        if token == 1:
            end = structure.find(b"\x00", position)
            require(end >= position and end - position <= 255, "FDT node name")
            try:
                name = structure[position:end].decode("ascii")
            except UnicodeDecodeError as error:
                raise ValueError("FDT non-ASCII node") from error
            require("/" not in name and (bool(name) if stack else name == ""), "FDT root/node name")
            position = (end + 4) & ~3
            require(position <= len(structure) and len(stack) < 64, "FDT node boundary/depth")
            stack.append(name)
            path = "/" + "/".join(stack[1:])
            require(path not in nodes_seen, "FDT duplicate node")
            nodes_seen.add(path)
            node_count += 1
        elif token == 2:
            require(bool(stack), "FDT unbalanced END_NODE")
            stack.pop()
        elif token == 3:
            require(bool(stack), "FDT property outside node")
            length, nameoff = struct.unpack(">II", block(structure, position, 8, "FDT property"))
            position += 8
            value = block(structure, position, length, "FDT property value")
            position = (position + length + 3) & ~3
            require(position <= len(structure) and nameoff < len(strings), "FDT property boundary")
            end = strings.find(b"\x00", nameoff)
            require(end > nameoff, "FDT property string offset")
            try:
                name = strings[nameoff:end].decode("ascii")
            except UnicodeDecodeError as error:
                raise ValueError("FDT non-ASCII property") from error
            path = "/" + "/".join(stack[1:])
            require((path, name) not in properties_seen, "FDT duplicate property")
            properties_seen.add((path, name))
            property_count += 1
            if len(stack) == 1:
                root_properties[name] = value
            if path == "/chosen" and name in ("bootargs", "stdout-path"):
                selected[path + "/" + name] = string_list(value, name)
            if len(stack) == 2 and name == "reg" and stack[-1].startswith("memory"):
                selected[path + "/" + name] = value.hex()
        elif token == 4:
            continue
        elif token == 9:
            require(not stack and node_count > 0 and position == len(structure), "FDT END boundary")
            ended = True
            break
        else:
            raise ValueError("FDT invalid structure token")
    require(ended, "FDT missing END")
    compatible = string_list(root_properties.get("compatible", b""), "FDT compatible")
    model = string_list(root_properties["model"], "FDT model") if "model" in root_properties else []
    return {**hashes(data), "version": version, "last_compatible_version": compatible_version,
            "boot_cpuid": cpu, "structure_offset": off_struct, "structure_bytes": struct_size,
            "strings_offset": off_strings, "strings_bytes": strings_size,
            "reserve_offset": off_reserve, "reservations": reservations,
            "node_count": node_count, "property_count": property_count,
            "root_compatible": compatible, "root_model": model,
            "other_root_properties_hex": {name: value.hex() for name, value in root_properties.items()
                                          if name not in ("compatible", "model")},
            "selected_properties": selected}


def inspect_concat_dtbs(data):
    position = 0
    result = []
    while position < len(data):
        require(len(result) < 64, "FDT concat count")
        magic, size = struct.unpack(">II", block(data, position, 8, "FDT concat header"))
        require(magic == 0xd00dfeed and size >= 40, "FDT concat magic/size")
        dtb = block(data, position, size, "FDT concat blob")
        result.append({"index": len(result), "offset": position, **inspect_fdt(dtb)})
        position += size
    require(bool(result) and position == len(data), "FDT concat consumption")
    return result


def inspect_resource(data):
    require(len(data) >= 512 and len(data) % 512 == 0, "RSCE size")
    magic, version, table_version, header_blocks, table_offset, entry_blocks, reserved, count = struct.unpack_from("<4sHHBBBBI", data)
    require(magic == b"RSCE" and version == table_version == 0 and
            header_blocks == table_offset == entry_blocks == 1 and reserved == 0, "RSCE header")
    require(0 < count <= 64 and (1 + count) * 512 <= len(data), "RSCE table bounds")
    zero(data[16:512], "RSCE header padding")
    entries = []
    paths = set()
    spans = []
    for index in range(count):
        record = block(data, (1 + index) * 512, 512, "RSCE entry")
        require(record[:4] == b"ENTR", "RSCE entry tag")
        path = ascii_string(record[4:224], "RSCE entry path")
        parts = PurePosixPath(path).parts
        require(path and not path.startswith("/") and "//" not in path and
                all(part not in ("", ".", "..") for part in path.split("/")) and
                all(character.isalnum() or character in "/._-" for character in path) and
                str(PurePosixPath(path)) == path and len(parts) <= 16, "RSCE unsafe path")
        require(path not in paths, "RSCE duplicate path")
        paths.add(path)
        hash_size, offset_blocks, size = struct.unpack_from("<III", record, 256)
        require(hash_size == 20 and size > 0, "RSCE unsupported hash or empty content")
        zero(record[244:256], "RSCE hash padding")
        zero(record[268:], "RSCE entry padding")
        offset = offset_blocks * 512
        require(offset >= (1 + count) * 512, "RSCE entry overlaps table")
        payload = block(data, offset, size, "RSCE payload")
        digest = hashlib.sha1(payload).digest()
        require(digest == record[224:244], "RSCE SHA1 mismatch")
        spans.append((offset, offset + size))
        content = {"index": index, "path": path, "offset": offset, **hashes(payload),
                   "stored_sha1": record[224:244].hex(), "hash_verified": True}
        if path.endswith(".dtb"):
            content["fdt"] = inspect_fdt(payload)
        else:
            require(path in ("logo.bmp", "logo_kernel.bmp") and payload[:2] == b"BM", "RSCE unsupported resource")
        entries.append(content)
    ordered = sorted(spans)
    cursor = (1 + count) * 512
    for start, end in ordered:
        require(cursor <= start, "RSCE payload overlap")
        zero(data[cursor:start], "RSCE content gap")
        cursor = end
    zero(data[cursor:], "RSCE tail padding")
    return {"version": version, "table_version": table_version, "header_blocks": header_blocks,
            "table_offset_blocks": table_offset, "entry_blocks": entry_blocks,
            "dtb_count": sum(record["path"].endswith(".dtb") for record in entries),
            "logo_count": sum(record["path"] in ("logo.bmp", "logo_kernel.bmp") for record in entries),
            "entries": entries}


def inspect_boot(data, expected_concat_count=11):
    require(expected_concat_count in (1, 11), "unsupported audit profile")
    require(1660 <= len(data) <= 64 * 1024 * 1024, "boot input size")
    require(data[:8] == b"ANDROID!", "boot magic")
    kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size, second_addr, tags_addr, page, version, os_version = struct.unpack_from("<10I", data, 8)
    recovery_size, recovery_offset, header_size, dtb_size, dtb_addr = struct.unpack_from("<IQIIQ", data, 1632)
    require(version == 2 and header_size == 1660 and page in (2048, 4096, 8192, 16384), "boot v2 header/page")
    require(recovery_size == recovery_offset == 0, "unsupported recovery dtbo")
    require(all(size > 0 for size in (kernel_size, ramdisk_size, second_size, dtb_size)), "empty boot component")
    board = ascii_string(data[48:64], "board")
    cmdline = ascii_string(data[64:576] + data[608:1632], "cmdline")
    zero(block(data, 1660, page - 1660, "header padding"), "header padding")
    components = []
    position = page
    image_sha1 = hashlib.sha1()
    for name, size in (("kernel", kernel_size), ("ramdisk", ramdisk_size), ("second", second_size)):
        payload = block(data, position, size, name)
        components.append({"name": name, "offset": position, **hashes(payload)})
        image_sha1.update(payload)
        image_sha1.update(struct.pack("<I", size))
        end = position + size
        aligned = (end + page - 1) & ~(page - 1)
        zero(block(data, end, aligned - end, name + " padding"), name + " padding")
        position = aligned
    image_sha1.update(struct.pack("<I", 0))
    payload = block(data, position, dtb_size, "dtb")
    components.append({"name": "dtb", "offset": position, **hashes(payload)})
    image_sha1.update(payload)
    image_sha1.update(struct.pack("<I", dtb_size))
    end = position + dtb_size
    aligned = (end + page - 1) & ~(page - 1)
    zero(block(data, end, aligned - end, "dtb padding"), "dtb padding")
    zero(data[aligned:], "partition tail")
    require(image_sha1.digest() == data[576:596], "boot ID SHA1 mismatch")
    zero(data[596:608], "boot ID padding")
    second = components[2]
    resource = inspect_resource(data[second["offset"]:second["offset"] + second["bytes"]])
    require(resource["dtb_count"] == 9 and resource["logo_count"] == 2, "original resource count")
    concatenated = inspect_concat_dtbs(payload)
    require(len(concatenated) == expected_concat_count, "profile concatenated DTB count")
    return {"schema": 1, "board_tested": False, "package": hashes(data),
            "raw_bytes": aligned, "partition_tail_bytes": len(data) - aligned,
            "header": {"version": version, "header_size": header_size, "page_size": page,
                       "kernel_addr": kernel_addr, "ramdisk_addr": ramdisk_addr,
                       "second_addr": second_addr, "tags_addr": tags_addr, "dtb_addr": dtb_addr,
                       "recovery_dtbo_bytes": recovery_size, "recovery_dtbo_offset": recovery_offset,
                       "os_version_encoded": os_version, "os_version": os_version >> 11,
                       "os_patch_level": os_version & 0x7ff,
                       "board": board, "cmdline": cmdline, "id_sha1": data[576:596].hex()},
            "components": components, "resource": resource, "concatenated_dtbs": concatenated}


def read_ordinary(path):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        information = os.fstat(fd)
        require(stat.S_ISREG(information.st_mode) and 0 < information.st_size <= 64 * 1024 * 1024,
                "input must be bounded ordinary file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(information.st_size + 1)
        require(len(data) == information.st_size, "input changed during read")
        return data
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = inspect_boot(read_ordinary(args.package))
    out = Path(args.out).resolve()
    require(out.is_relative_to(HERE / "build"), "audit output outside own build")
    out.mkdir(parents=True, exist_ok=False)
    report["auditor_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "BOOT_V2_OFFLINE_FORMAT_VERIFIED",
                      "package": report["package"], "raw_bytes": report["raw_bytes"],
                      "rsce_dtbs": report["resource"]["dtb_count"],
                      "rsce_logos": report["resource"]["logo_count"],
                      "concat_dtbs": len(report["concatenated_dtbs"]), "board_tested": False}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
