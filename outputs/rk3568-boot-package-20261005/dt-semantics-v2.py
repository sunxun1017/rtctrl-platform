#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded full FDT semantic map, including every node/property and reservation."""
import struct


def require(value, message):
    if not value:
        raise ValueError(message)


def block(data, offset, size):
    require(0 <= offset <= len(data) and 0 <= size <= len(data) - offset, "FDT integer/range boundary")
    return data[offset:offset + size]


def parse(data):
    require(40 <= len(data) <= 1024 * 1024, "FDT bounded size")
    magic, total, st, strings, reserve, version, last, cpu, ns, nt = struct.unpack_from(">10I", data)
    require(magic == 0xd00dfeed and total == len(data) and version == 17 and last == 16, "FDT header")
    require(st >= 40 and st % 4 == 0 and strings >= 40 and reserve >= 40 and reserve % 8 == 0, "FDT offsets")
    tree, names = block(data, st, nt), block(data, strings, ns)
    pairs = []
    position = reserve
    while True:
        address, size = struct.unpack(">QQ", block(data, position, 16))
        position += 16
        if address == size == 0:
            break
        require(len(pairs) < 256 and size > 0 and address <= 0xffffffffffffffff - size, "FDT reservation overflow")
        pairs.append([address, size])
    ranges = sorted([(0, 40), (reserve, position), (st, st + nt), (strings, strings + ns)])
    require(all(left[1] <= right[0] for left, right in zip(ranges, ranges[1:])), "FDT sections overlap")
    stack, nodes, props = [], set(), {}
    position = 0
    ended = False
    while position < len(tree):
        token = struct.unpack(">I", block(tree, position, 4))[0]
        position += 4
        if token == 1:
            end = tree.find(b"\0", position)
            require(end >= position and end - position <= 255, "FDT node length")
            name = tree[position:end].decode("ascii")
            require("/" not in name and (name if stack else name == "") and len(stack) < 64, "FDT node name/depth")
            position = (end + 4) & ~3
            block(tree, end + 1, position - end - 1)
            stack.append(name)
            path = "/" + "/".join(stack[1:])
            require(path not in nodes, "FDT duplicate node")
            nodes.add(path)
        elif token == 2:
            require(stack, "FDT unbalanced END_NODE")
            stack.pop()
        elif token == 3:
            require(stack, "FDT property outside node")
            size, nameoff = struct.unpack(">II", block(tree, position, 8))
            position += 8
            value = block(tree, position, size)
            position = (position + size + 3) & ~3
            require(position <= len(tree) and nameoff < len(names), "FDT property boundary")
            end = names.find(b"\0", nameoff)
            require(end > nameoff, "FDT property name")
            name = names[nameoff:end].decode("ascii")
            path = "/" + "/".join(stack[1:])
            key = path + ":" + name
            require(key not in props, "FDT duplicate property")
            props[key] = value.hex()
        elif token == 4:
            continue
        elif token == 9:
            require(not stack and position == len(tree), "FDT END boundary")
            ended = True
            break
        else:
            raise ValueError("FDT bad token")
    require(ended and "/" in nodes, "FDT missing END/root")
    return {"nodes": sorted(nodes), "properties": props, "reservations": pairs,
            "boot_cpuid": cpu, "version": version, "last_compatible_version": last}


def diff(before, after):
    require(before["nodes"] == after["nodes"], "FDT nodes changed")
    for key in ("reservations", "boot_cpuid", "version", "last_compatible_version"):
        require(before[key] == after[key], "FDT metadata changed: " + key)
    return {key: {"before": before["properties"].get(key), "after": after["properties"].get(key)}
            for key in sorted(before["properties"].keys() | after["properties"].keys())
            if before["properties"].get(key) != after["properties"].get(key)}


def phandles(tree):
    found, by_node = {}, {}
    for key, value in tree["properties"].items():
        path, name = key.rsplit(":", 1)
        if name not in ("phandle", "linux,phandle"):
            continue
        require(len(value) == 8, "Malformed phandle length")
        handle = int(value, 16)
        require(0 < handle < 0xffffffff, "Invalid phandle value")
        require(handle not in found or found[handle] == path, "Conflicting phandle")
        require(path not in by_node or by_node[path] == handle, "Node phandle aliases disagree")
        found[handle], by_node[path] = path, handle
    return found


SHIM_DIFF = {"/__symbols__:chosen": {"before": None, "after": b"/chosen\0".hex()},
             "/chosen:phandle": {"before": None, "after": "000002f9"}}
BOOT_DEVICES = b"androidboot.boot_devices=fe310000.sdhci,fe330000.nandc\0"


def overlay_diff(reboot_path):
    return {**SHIM_DIFF, "/chosen:bootargs_ext": {"before": None, "after": BOOT_DEVICES.hex()},
            reboot_path + ":mode-bootloader": {"before": "5242c301", "after": "5242c309"},
            reboot_path + ":mode-fastboot": {"before": "5242c309", "after": "5242c303"}}
