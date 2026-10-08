#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real libfdt overlay reproducer; no simulated apply or fake successful base."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LIB_SOURCE = ROOT / "third_party/linux-rk3588/scripts/dtc/libfdt"
UART = ROOT / "outputs/rk3568-motor-alignment-20261004/uart.dtb"
DTBO = ROOT / "outputs/rk3568-backup-linux-20261003/original/dtbo.img"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compile_real_lib(out):
    source = out / "libfdt-source"
    source.mkdir()
    names = sorted(p.name for p in LIB_SOURCE.iterdir() if p.suffix in (".h", ".c"))
    pins = json.loads((HERE / "source-lock-v2.json").read_text())["sources"]
    assert set(names) == set(pins)
    for name in names:
        assert sha((LIB_SOURCE / name).read_bytes()) == pins[name]
        shutil.copyfile(LIB_SOURCE / name, source / name)
    target = out / "libfdt-real.so"
    command = ["gcc", "-std=gnu11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror", "-I", str(source)]
    command += [str(source / name) for name in names if name.endswith(".c")]
    command += ["-o", str(target)]
    process = subprocess.run(command, capture_output=True, timeout=90)
    (out / "compile.stdout").write_bytes(process.stdout)
    (out / "compile.stderr").write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode()
    assert sha(target.read_bytes()) == "03c8661fb005cd967c768332622c6aed6415dbcdce31939de26933e61b388a18"
    (out / "libfdt-manifest.json").write_text(json.dumps({"command": command, "binary_sha256": sha(target.read_bytes()),
        "sources": {name: sha((source / name).read_bytes()) for name in names}}, indent=2) + "\n")
    return target


class Real:
    def __init__(self, path):
        self.lib = ctypes.CDLL(str(path))
        declarations = {"fdt_open_into": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
            "fdt_path_offset": ([ctypes.c_void_p, ctypes.c_char_p], ctypes.c_int),
            "fdt_setprop": ([ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
            "fdt_overlay_apply": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int)}
        for name, (arguments, returns) in declarations.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = arguments, returns

    def base(self, data):
        source = ctypes.create_string_buffer(data)
        target = ctypes.create_string_buffer(len(data) + 65536)
        assert self.lib.fdt_open_into(source, target, len(target)) == 0
        return target

    def property(self, base, path, name, value):
        node = self.lib.fdt_path_offset(base, path.encode())
        assert node >= 0
        data = ctypes.create_string_buffer(value)
        assert self.lib.fdt_setprop(base, node, name.encode(), data, len(value)) == 0

    def apply(self, data, overlay, symbol=False):
        base = self.base(data)
        if symbol:
            self.property(base, "/__symbols__", "chosen", b"/chosen\0")
        before = bytes(base)
        real_overlay = ctypes.create_string_buffer(overlay)
        status = self.lib.fdt_overlay_apply(base, real_overlay)
        corrupted = bytes(base)
        # This fixture restores a real backup and keeps the actual failure code.
        if status:
            ctypes.memmove(base, before, len(before))
        return {"status": status, "before_magic": before[:4].hex(), "after_apply_magic": corrupted[:4].hex(),
                "restored_exact": bytes(base) == before, "success": status == 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--shim")
    args = parser.parse_args()
    out = Path(args.out).absolute()
    assert out == out.resolve() and out.is_relative_to(HERE / "build")
    out.mkdir(parents=True, exist_ok=False)
    uart, dtbo = UART.read_bytes(), DTBO.read_bytes()
    assert len(uart) == 162414 and sha(uart) == "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1"
    assert len(dtbo) == 4194304 and sha(dtbo) == "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d"
    assert struct.unpack_from(">8I", dtbo) == (0xd7b7ab1e, 623, 32, 32, 1, 32, 2048, 0)
    assert struct.unpack_from(">8I", dtbo, 32) == (559, 64, 0, 0, 0, 0, 0, 0)
    overlay = dtbo[64:623]
    assert sha(overlay) == "acf746c91caa230f7958ba2df4e6daf325881e7bce855657aa3b535f440dfec3"
    assert not any(dtbo[623:])
    real = Real(compile_real_lib(out))
    cases = []
    for name, data, symbol, want_success in (
        ("original-uart-actual-apply-fails-and-restores", uart, False, False),
        ("symbol-only-actual-apply-fails-and-restores", uart, True, False),
        ("complete-production-shim-actual-apply-succeeds",
         Path(args.shim).read_bytes() if args.shim else uart, False, True)):
        result = real.apply(data, overlay, symbol)
        passed = result["success"] == want_success
        if not want_success:
            passed = passed and result["status"] == -1 and result["after_apply_magic"] == "ffffffff" and result["restored_exact"]
        cases.append({"name": name, "passed": passed, **result})
    report = {"total": len(cases), "passed": sum(case["passed"] for case in cases), "cases": cases,
              "test_sha256": sha(Path(__file__).read_bytes()), "uart_sha256": sha(uart), "overlay_sha256": sha(overlay),
              "real_libfdt_no_mock": True, "board_tested": False}
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
