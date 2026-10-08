#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Freeze real overlay evidence, local tool/source and the new RAM-only v2 package."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def metadata(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "crc32": f"{zlib.crc32(data) & 0xffffffff:08x}"}


def verify_old_receipt(name):
    base = HERE / "build" / name
    receipt = json.loads((base / "receipt.json").read_text())
    for relative, expected in receipt["source_snapshot"].items():
        actual = metadata(base / "source-snapshot" / relative)
        assert all(actual[k] == value for k, value in expected.items())
    for relative, expected in receipt["evidence"].items():
        actual = metadata(ROOT / relative)
        assert all(actual[k] == value for k, value in expected.items())
    return metadata(base / "receipt.json")


def main():
    production = HERE / "build/ram-candidate-v2"
    shim = HERE / "build/uart-shim-v2"
    commands = [
        [sys.executable, "-B", str(HERE / "test-uart-shim-v2.py"), "--out", str(HERE / "build/shim-final-tests-v2"),
         "--shim", str(shim / "uart-ram-shim.dtb")],
        [sys.executable, "-B", str(HERE / "test-shim-boundaries-v2.py"), "--out", str(HERE / "build/shim-boundaries-final-v2")],
        [sys.executable, "-B", str(HERE / "test-ram-candidate-v2.py"), "--out", str(HERE / "build/candidate-freeze-tests-v2")],
        [sys.executable, "-B", str(HERE / "build-ram-candidate-v2.py"), "--out", str(production)],
        [sys.executable, "-B", str(HERE / "audit-ram-candidate-v2.py"), "--package", str(production / "boot-padded.img"),
         "--out", str(HERE / "build/independent-candidate-v2")],
        [sys.executable, "-B", str(HERE / "crosscheck-dt.py"), "--ram-candidate", "--roundtrip", str(production),
         "--out", str(HERE / "build/dtc-candidate-v2")]]
    for command in commands:
        subprocess.run(command, check=True, timeout=180)
    expected = {"shim-red-v2": (2, 3), "shim-green-v2": (3, 3), "shim-final-tests-v2": (3, 3),
        "shim-boundaries-v2": (39, 39), "shim-boundaries-final-v2": (39, 39), "candidate-red-v2": (2, 43),
        "candidate-green-v2": (43, 43), "candidate-final-tests-v2": (45, 45), "candidate-freeze-tests-v2": (45, 45),
        "dtc-candidate-v2": (10, 10)}
    for name, want in expected.items():
        result = json.loads((HERE / "build" / name / "results.json").read_text())
        assert (result["passed"], result["total"]) == want
    old = {name: verify_old_receipt(name) for name in ("original-freeze-v1", "candidate-freeze-v1")}
    original = ROOT / "outputs/rk3568-backup-linux-20261003/original/boot.img"
    assert original.read_bytes() == (HERE / "build/roundtrip-v1/boot-padded.img").read_bytes()
    manifest = json.loads((production / "manifest.json").read_text())
    independent = json.loads((HERE / "build/independent-candidate-v2/audit.json").read_text())
    assert independent["package"]["sha256"] == manifest["artifacts"]["boot-padded.img"]["sha256"]
    for name, want in manifest["artifacts"].items():
        assert metadata(production / name) == want
    for name, want in manifest["source_inputs"].items():
        assert metadata(production / "source-inputs" / name) == want
    target = HERE / "build/candidate-freeze-v2"
    target.mkdir(exist_ok=False)
    snapshot = target / "source-snapshot"
    snapshot.mkdir()
    for source in HERE.iterdir():
        if source.is_file():
            shutil.copyfile(source, snapshot / source.name)
    shutil.copytree(HERE / "sources", snapshot / "sources")
    shutil.copytree(HERE / "build/libfdt-v2", target / "tool-snapshot")
    shutil.copytree(shim, target / "shim-snapshot")
    shutil.copytree(HERE / "build/shim-test-history-v2", target / "red-test-source")
    evidence_paths = [HERE / "build" / name / "results.json" for name in expected]
    evidence_paths += [production / "manifest.json", production / "audit.json", shim / "manifest.json",
        HERE / "build/libfdt-v2/manifest.json", HERE / "build/independent-candidate-v2/audit.json",
        HERE / "build/shim-boundaries-final-v2/native-overflow.json",
        HERE / "build/shim-boundaries-final-v2/native-partial.json"]
    receipt = {"schema": 2, "status": "RAM_ONLY_NOT_FLASH_READY_V2_FROZEN_OFFLINE", "board_tested": False,
        "flash_authorized": False, "saveenv": False, "artifacts": manifest["artifacts"],
        "inputs": manifest["inputs"], "rootfs": manifest["rootfs"], "original_dtbo": manifest["original_dtbo"],
        "real_overlay": manifest["real_overlay"], "packaged_dtb_is_pre_overlay_shim": True,
        "original_boot_unchanged": metadata(original), "old_receipts_verified_unchanged": old,
        "source_snapshot": {str(p.relative_to(snapshot)): metadata(p) for p in sorted(snapshot.rglob("*")) if p.is_file()},
        "tool_and_shim_snapshot": {str(p.relative_to(target)): metadata(p) for name in
            ("tool-snapshot", "shim-snapshot", "red-test-source") for p in sorted((target / name).rglob("*")) if p.is_file()},
        "evidence": {str(p.relative_to(ROOT)): metadata(p) for p in evidence_paths},
        "tests": {"real-overlay-red-green": "2/3 -> 3/3", "semantic-native-boundaries": "39/39",
                  "candidate": "45/45", "independent_dtc": "10/10"},
        "commands": commands, "address_analysis": manifest["address_analysis"],
        "full_semantic_parser": {"file": "outputs/rk3568-boot-package-20261005/dt-semantics-v2.py", "entry": "parse(bytes)",
            "fields": ["nodes", "properties", "reservations", "boot_cpuid", "version", "last_compatible_version"]},
        "applied_audit_only_path": "outputs/rk3568-boot-package-20261005/build/uart-shim-v2/applied-once-audit-only.dtb",
        "not_covered": ["exact deployed U-Boot libfdt code equivalence", "live bootm DT/hash and final command line",
            "actual relocation/reserved spans/ARM64 entry", "RAM candidate execution", "early resource DT flash compatibility",
            "USB recovery", "WiFi/PCM/MCU START"]}
    (target / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": metadata(target / "receipt.json"), "manifest": metadata(production / "manifest.json"),
                      "artifacts": manifest["artifacts"]}))


if __name__ == "__main__":
    main()
