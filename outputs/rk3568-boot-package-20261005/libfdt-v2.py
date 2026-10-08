#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded calls to the SHA-locked real libfdt; failures stay failures after restore."""
import ctypes
import hashlib
import importlib.util
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
LIB_SHA = "03c8661fb005cd967c768332622c6aed6415dbcdce31939de26933e61b388a18"


def semantics():
    spec = importlib.util.spec_from_file_location("full_fdt_semantics_v2", HERE / "dt-semantics-v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RealLibFdt:
    def __init__(self):
        path = HERE / "build/libfdt-v2/libfdt-locked.so"
        if hashlib.sha256(path.read_bytes()).hexdigest() != LIB_SHA:
            raise ValueError("Locked libfdt binary SHA mismatch")
        self.lib = ctypes.CDLL(str(path))
        functions = {
            "fdt_open_into": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
            "fdt_path_offset": ([ctypes.c_void_p, ctypes.c_char_p], ctypes.c_int),
            "fdt_setprop": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
            "fdt_delprop": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p], ctypes.c_int),
            "fdt_del_node": ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
            "fdt_pack": ([ctypes.c_void_p], ctypes.c_int),
            "fdt_overlay_apply": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int)}
        for name, (args, returns) in functions.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, returns

    def opened(self, data, extra=65536):
        semantics().parse(data)
        if not 0 <= extra <= 65536 or len(data) + extra > 1024 * 1024:
            raise ValueError("FDT capacity overflow")
        source, target = ctypes.create_string_buffer(data), ctypes.create_string_buffer(len(data) + extra)
        status = self.lib.fdt_open_into(source, target, len(target))
        if status:
            raise ValueError("Real fdt_open_into error " + str(status))
        return target

    def node(self, base, path):
        if not path.startswith("/") or "\0" in path or len(path) > 4096:
            raise ValueError("FDT node path")
        node = self.lib.fdt_path_offset(base, path.encode("ascii"))
        if node < 0:
            raise ValueError("Real fdt_path_offset error " + str(node))
        return node

    def set_property(self, base, path, name, value):
        if not name or "\0" in name or len(name) > 255 or len(value) > 65536:
            raise ValueError("FDT property capacity")
        data = ctypes.create_string_buffer(value)
        status = self.lib.fdt_setprop(base, self.node(base, path), name.encode("ascii"), data, len(value))
        if status:
            raise ValueError("Real fdt_setprop error " + str(status))

    def packed(self, base):
        status = self.lib.fdt_pack(base)
        if status:
            raise ValueError("Real fdt_pack error " + str(status))
        size = struct.unpack_from(">I", bytes(base), 4)[0]
        if not 40 <= size <= len(base):
            raise ValueError("Packed FDT size")
        data = bytes(base)[:size]
        semantics().parse(data)
        return data

    def apply(self, data, overlay):
        semantics().parse(overlay)
        base = self.opened(data)
        before = bytes(base)
        fdto = ctypes.create_string_buffer(overlay)
        status = self.lib.fdt_overlay_apply(base, fdto)
        after = bytes(base)
        if status:
            ctypes.memmove(base, before, len(before))
        report = {"status": status, "success": status == 0,
                  "after_apply_magic": after[:4].hex(), "overlay_after_magic": bytes(fdto)[:4].hex(),
                  "backup_sha256": hashlib.sha256(before).hexdigest(),
                  "after_apply_sha256": hashlib.sha256(after).hexdigest(),
                  "restored_exact": status != 0 and bytes(base) == before,
                  "restored_sha256": hashlib.sha256(bytes(base)).hexdigest() if status else None,
                  "failure_code_preserved_after_restore": status != 0}
        # A caller must inspect status; no damaged/failed tree is returned as an applied result.
        return report, self.packed(base) if status == 0 else None


def create_shim(original):
    semantic = semantics()
    before = semantic.parse(original)
    semantic.require("/chosen" in before["nodes"] and "/__symbols__" in before["nodes"], "Missing shim target node")
    semantic.require("/chosen:phandle" not in before["properties"] and
                     "/chosen:linux,phandle" not in before["properties"] and
                     "/__symbols__:chosen" not in before["properties"], "Shim target already assigned")
    handles = semantic.phandles(before)
    semantic.require(handles and max(handles) == 0x2f8 and 0x2f9 not in handles, "Shim phandle allocation conflict/overflow")
    semantic.require(before["reservations"] == [[0xa100000, 0x25000], [0xa200000, 0xc8c20]], "Original reserve map changed")
    real = RealLibFdt()
    base = real.opened(original)
    real.set_property(base, "/__symbols__", "chosen", b"/chosen\0")
    real.set_property(base, "/chosen", "phandle", struct.pack(">I", 0x2f9))
    result = real.packed(base)
    after = semantic.parse(result)
    semantic.require(semantic.diff(before, after) == semantic.SHIM_DIFF, "Unexpected shim semantic change")
    semantic.phandles(after)
    return result
