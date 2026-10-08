#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the two-property RAM shim, apply real entry0 once, and seal full semantic diff."""
import argparse
import importlib.util
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def overlay_entry(dtbo):
    semantic = load("dt-semantics-v2.py")
    semantic.require(len(dtbo) == 4194304, "DTBO complete partition size")
    semantic.require(struct.unpack_from(">8I", dtbo) == (0xd7b7ab1e, 623, 32, 32, 1, 32, 2048, 0), "DTBO header overflow/layout")
    semantic.require(struct.unpack_from(">8I", dtbo, 32) == (559, 64, 0, 0, 0, 0, 0, 0), "DTBO entry overflow/layout")
    semantic.require(not any(dtbo[623:]), "DTBO nonzero tail")
    blob = dtbo[64:623]
    semantic.require(load("build-roundtrip.py").sha(blob) == "acf746c91caa230f7958ba2df4e6daf325881e7bce855657aa3b535f440dfec3", "DTBO blob SHA mismatch")
    semantic.parse(blob)
    return blob


def validate_transition(original, applied):
    semantic = load("dt-semantics-v2.py")
    before, after = semantic.parse(original), semantic.parse(applied)
    reboot = [key.rsplit(":", 1)[0] for key in before["properties"] if key.endswith(":mode-normal")]
    semantic.require(len(reboot) == 1, "Exact reboot node identity")
    difference = semantic.diff(before, after)
    semantic.require(difference == semantic.overlay_diff(reboot[0]), "Unexpected full overlay semantic change")
    semantic.require(after["properties"][reboot[0] + ":mode-normal"] == "5242c300", "Normal reboot mode changed")
    semantic.require(after["reservations"] == [[0xa100000, 0x25000], [0xa200000, 0xc8c20]], "Overlay reserve map changed")
    semantic.phandles(before)
    semantic.phandles(after)
    return difference


def build(out):
    out = Path(out).absolute()
    if out != out.resolve() or not out.is_relative_to(HERE / "build"):
        raise ValueError("Fresh ordinary own build path required")
    common = load("build-roundtrip.py")
    uart = common.read_locked(ROOT / "outputs/rk3568-motor-alignment-20261004/uart.dtb", 162414,
        "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1")
    dtbo = common.read_locked(ROOT / "outputs/rk3568-backup-linux-20261003/original/dtbo.img", 4194304,
        "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d")
    bridge = load("libfdt-v2.py")
    shim = bridge.create_shim(uart)
    overlay = overlay_entry(dtbo)
    apply_report, applied = bridge.RealLibFdt().apply(shim, overlay)
    if apply_report["status"] or applied is None:
        raise ValueError("Real overlay failed, no shim accepted")
    difference = validate_transition(uart, applied)
    out.mkdir(parents=True, exist_ok=False)
    common.write_new(out / "uart-ram-shim.dtb", shim)
    common.write_new(out / "overlay-entry0.dtbo", overlay)
    common.write_new(out / "applied-once-audit-only.dtb", applied)
    semantic = load("dt-semantics-v2.py")
    for name, data in (("before", uart), ("shim", shim), ("applied", applied)):
        common.write_new(out / (name + "-semantics.json"), (json.dumps(semantic.parse(data), indent=2) + "\n").encode())
    manifest = {"schema": 1, "status": "RAM_SHIM_REAL_LIBFDT_OVERLAY_VERIFIED_OFFLINE",
        "packaged_blob": "uart-ram-shim.dtb", "applied_blob_is_audit_only_never_packaged": True,
        "original_uart": common.metadata(uart), "original_dtbo": common.metadata(dtbo),
        "overlay_entry0": common.metadata(overlay), "shim": common.metadata(shim), "applied": common.metadata(applied),
        "libfdt_sha256": bridge.LIB_SHA, "shim_diff": semantic.diff(semantic.parse(uart), semantic.parse(shim)),
        "complete_applied_diff": difference, "apply": apply_report,
        "reservations_preserved": True, "existing_phandles_unchanged": True,
        "board_tested": False, "flash_authorized": False, "exact_deployed_uboot_libfdt": False,
        "source_inputs": {name: common.metadata((HERE / name).read_bytes()) for name in
            ("PLAN-v2.md", "source-lock-v2.json", "dt-semantics-v2.py", "libfdt-v2.py", "build-uart-shim-v2.py")}}
    common.write_new(out / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print(json.dumps({"shim": manifest["shim"], "applied": manifest["applied"], "full_diff_count": len(difference)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        build(args.out)
    except (OSError, ValueError) as error:
        parser.exit(1, "UART_SHIM_REJECTED: " + str(error) + "\n")


if __name__ == "__main__":
    main()
