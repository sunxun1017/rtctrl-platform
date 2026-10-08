#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real-libfdt mutations exercise shim gates, native errors and full-tree policy."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reject(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Invalid tree/input was accepted")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).absolute()
    assert out == out.resolve() and out.is_relative_to(HERE / "build")
    out.mkdir(parents=True, exist_ok=False)
    semantic, bridge, builder = [load(name) for name in ("dt-semantics-v2.py", "libfdt-v2.py", "build-uart-shim-v2.py")]
    real = bridge.RealLibFdt()
    original = (ROOT / "outputs/rk3568-motor-alignment-20261004/uart.dtb").read_bytes()
    dtbo = (ROOT / "outputs/rk3568-backup-linux-20261003/original/dtbo.img").read_bytes()
    shimdir = HERE / "build/uart-shim-v2"
    shim = (shimdir / "uart-ram-shim.dtb").read_bytes()
    applied = (shimdir / "applied-once-audit-only.dtb").read_bytes()
    overlay = (shimdir / "overlay-entry0.dtbo").read_bytes()
    cases = []

    def run(name, call):
        try:
            call()
            cases.append({"name": name, "passed": True})
        except Exception as error:
            cases.append({"name": name, "passed": False, "error": type(error).__name__ + ": " + str(error)})

    def mutate(data, path, name, value):
        base = real.opened(data)
        real.set_property(base, path, name, value)
        return real.packed(base)

    def delete_node(data, path):
        base = real.opened(data)
        assert real.lib.fdt_del_node(base, real.node(base, path)) == 0
        return real.packed(base)

    def literal_diff():
        old, before_apply, after = map(semantic.parse, (original, shim, applied))
        assert len(old["nodes"]) == 958 and len(old["properties"]) == 4859
        assert old["nodes"] == before_apply["nodes"] == after["nodes"]
        assert old["reservations"] == before_apply["reservations"] == after["reservations"] == [[0xa100000, 0x25000], [0xa200000, 0xc8c20]]
        extra = {"/__symbols__:chosen": b"/chosen\0".hex(), "/chosen:phandle": "000002f9"}
        assert {k: v for k, v in before_apply["properties"].items() if k not in extra} == old["properties"]
        assert all(before_apply["properties"][k] == v for k, v in extra.items())
        want = {**extra, "/chosen:bootargs_ext": b"androidboot.boot_devices=fe310000.sdhci,fe330000.nandc\0".hex(),
            "/syscon@fdc20000/reboot-mode:mode-bootloader": "5242c309",
            "/syscon@fdc20000/reboot-mode:mode-fastboot": "5242c303"}
        assert {k: v for k, v in after["properties"].items() if k not in want} == {
            k: v for k, v in old["properties"].items() if k not in want}
        assert all(after["properties"][k] == v for k, v in want.items())
        assert after["properties"]["/syscon@fdc20000/reboot-mode:mode-normal"] == "5242c300"
        assert max(semantic.phandles(old)) == 0x2f8 and semantic.phandles(after)[0x2f9] == "/chosen"

    run("literal-whole-tree-five-changes-reservations-existing-handles", literal_diff)
    run("deterministic-production-shim-bytes", lambda: (bridge.create_shim(original) == shim) or (_ for _ in ()).throw(AssertionError("Shim drift")))
    run("real-entry0-extracted-exact", lambda: (builder.overlay_entry(dtbo) == overlay) or (_ for _ in ()).throw(AssertionError("Overlay drift")))
    for path in ("/chosen", "/__symbols__"):
        run("reject-missing-node-" + path, lambda p=path: reject(lambda: bridge.create_shim(delete_node(original, p))))
    for name, path, prop, value in (
        ("chosen-existing-handle", "/chosen", "phandle", struct.pack(">I", 0x2f9)),
        ("chosen-linux-handle", "/chosen", "linux,phandle", struct.pack(">I", 0x2f9)),
        ("symbol-already-present", "/__symbols__", "chosen", b"/chosen\0"),
        ("duplicate-existing-handle", "/fiq-debugger", "phandle", struct.pack(">I", 0x2f8)),
        ("new-handle-conflict", "/wireless-wlan", "phandle", struct.pack(">I", 0x2f9)),
        ("handle-zero", "/wireless-wlan", "phandle", bytes(4)),
        ("handle-ffffffff", "/wireless-wlan", "phandle", struct.pack(">I", 0xffffffff)),
        ("handle-overflow-allocation", "/wireless-wlan", "phandle", struct.pack(">I", 0xfffffffe)),
        ("handle-bad-length", "/wireless-wlan", "phandle", bytes(3)),
        ("handle-alias-disagrees", "/wireless-wlan", "linux,phandle", struct.pack(">I", 0x2f7))):
        run("reject-" + name, lambda p=path, n=prop, v=value: reject(lambda: bridge.create_shim(mutate(original, p, n, v))))

    def bad_fdt(offset, value):
        data = bytearray(original)
        data[offset:offset + len(value)] = value
        reject(lambda: bridge.create_shim(bytes(data)))

    for name, offset, value in (("total", 4, struct.pack(">I", 0xffffffff)),
                                ("structure-offset", 8, struct.pack(">I", 0xfffffffc)),
                                ("strings-length", 32, struct.pack(">I", 0xffffffff)),
                                ("structure-length", 36, struct.pack(">I", 0xffffffff))):
        run("reject-fdt-integer-boundary-" + name, lambda o=offset, v=value: bad_fdt(o, v))
    reserve_offset = struct.unpack_from(">I", original, 16)[0]
    run("reject-reserve-64-bit-overflow", lambda: bad_fdt(reserve_offset, struct.pack(">QQ", 0xfffffffffffffff0, 0x20)))
    run("reject-libfdt-open-capacity-overflow", lambda: reject(lambda: real.opened(original, extra=0x7fffffff)))
    for name, offset in (("count", 16), ("entry-offset", 20), ("payload-size", 32), ("payload-offset", 36)):
        def altered_dtbo(off=offset):
            data = bytearray(dtbo)
            struct.pack_into(">I", data, off, 0xffffffff)
            reject(lambda: builder.overlay_entry(bytes(data)))
        run("reject-dtbo-integer-overflow-" + name, altered_dtbo)
    run("reject-dtbo-truncated", lambda: reject(lambda: builder.overlay_entry(dtbo[:622])))
    run("reject-dtbo-nonzero-tail", lambda: reject(lambda: builder.overlay_entry(dtbo[:-1] + b"x")))

    def native_failure(kind):
        if kind == "overflow":
            bad_overlay = mutate(overlay, "/fragment@0/__overlay__", "phandle", struct.pack(">I", 0xffffff00))
        else:
            base = real.opened(overlay)
            assert real.lib.fdt_delprop(base, real.node(base, "/__fixups__"), b"reboot_mode") == 0
            bad_overlay = real.packed(base)
        result, failed_tree = real.apply(shim, bad_overlay)
        (out / ("native-" + kind + ".json")).write_text(json.dumps(result, indent=2) + "\n")
        assert result["status"] < 0 and result["after_apply_magic"] == "ffffffff"
        assert result["restored_exact"] and result["backup_sha256"] == result["restored_sha256"]
        assert result["failure_code_preserved_after_restore"] and failed_tree is None
        if kind == "overflow":
            assert result["status"] == -17

    run("native-phandle-overflow-error-restore-no-applied-tree", lambda: native_failure("overflow"))
    run("native-missing-second-fixup-partial-merge-restores-error", lambda: native_failure("partial"))
    for name, path, prop, value in (
        ("status", "/wireless-wlan", "status", b"disabled\0"),
        ("existing-handle", "/wireless-wlan", "phandle", struct.pack(">I", 0x2fa)),
        ("initrd", "/chosen", "linux,initrd-start", struct.pack(">Q", 0x4000000)),
        ("bootargs", "/chosen", "bootargs", b"root=/dev/evil\0"),
        ("normal-reboot", "/syscon@fdc20000/reboot-mode", "mode-normal", struct.pack(">I", 0x5242c301)),
        ("wrong-shim-handle", "/chosen", "phandle", struct.pack(">I", 0x2fa)),
        ("power-extra", "/wireless-wlan", "arbitrary-power-change", bytes(4))):
        run("reject-applied-extra-change-" + name, lambda p=path, n=prop, v=value: reject(lambda: builder.validate_transition(original, mutate(applied, p, n, v))))
    run("reject-applied-node-deletion", lambda: reject(lambda: builder.validate_transition(original, delete_node(applied, "/wireless-wlan"))))
    def altered_reserve():
        data = bytearray(applied)
        offset = struct.unpack_from(">I", data, 16)[0]
        struct.pack_into(">Q", data, offset + 8, 0x25001)
        reject(lambda: builder.validate_transition(original, bytes(data)))
    run("reject-applied-memreserve-change", altered_reserve)

    def real_cli():
        target = out / "rebuilt-shim"
        command = [sys.executable, "-B", str(HERE / "build-uart-shim-v2.py"), "--out", str(target)]
        result = subprocess.run(command, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr.decode()
        assert (target / "uart-ram-shim.dtb").read_bytes() == shim
        result = subprocess.run(command, capture_output=True, timeout=60)
        assert result.returncode != 0 and (target / "uart-ram-shim.dtb").read_bytes() == shim
    run("real-shim-builder-cli-and-refuse-overwrite", real_cli)
    report = {"total": len(cases), "passed": sum(case["passed"] for case in cases), "cases": cases,
        "libfdt_sha256": bridge.LIB_SHA, "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in
            ("dt-semantics-v2.py", "libfdt-v2.py", "build-uart-shim-v2.py")}, "no_mock": True, "board_tested": False}
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"total": report["total"], "passed": report["passed"]}))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
