#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Freeze new RAM-only package and independent evidence without touching old builds."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def metadata(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    production = HERE / "build/ram-candidate-v1"
    commands = [
        [sys.executable, "-B", str(HERE / "test-ram-candidate.py"), "--out", str(HERE / "build/candidate-freeze-tests-v1")],
        [sys.executable, "-B", str(HERE / "build-ram-candidate.py"), "--out", str(production)],
        [sys.executable, "-B", str(HERE / "audit-ram-candidate.py"), "--package", str(production / "boot-padded.img"),
         "--out", str(HERE / "build/independent-candidate-v1")],
        [sys.executable, "-B", str(HERE / "crosscheck-dt.py"), "--ram-candidate", "--roundtrip", str(production),
         "--out", str(HERE / "build/dtc-candidate-v1")]]
    for command in commands:
        subprocess.run(command, check=True, timeout=180)
    for name, passed, total in (("candidate-red-v1", 1, 38), ("candidate-green-v1", 38, 38),
                                 ("candidate-final-tests-v1", 43, 43), ("candidate-freeze-tests-v1", 43, 43),
                                 ("original-regression-v1", 42, 42)):
        result = json.loads((HERE / "build" / name / "results.json").read_text())
        assert result["passed"] == passed and result["total"] == total
    target = HERE / "build/candidate-freeze-v1"
    target.mkdir(exist_ok=False)
    snapshot = target / "source-snapshot"
    snapshot.mkdir()
    for source in HERE.iterdir():
        if source.is_file():
            shutil.copyfile(source, snapshot / source.name)
    shutil.copytree(HERE / "sources", snapshot / "sources")
    manifest = json.loads((production / "manifest.json").read_text())
    independent = json.loads((HERE / "build/independent-candidate-v1/audit.json").read_text())
    assert manifest["artifacts"]["boot-padded.img"]["sha256"] == independent["package"]["sha256"]
    evidence_paths = [production / "manifest.json", production / "audit.json",
                      HERE / "build/independent-candidate-v1/audit.json",
                      HERE / "build/dtc-candidate-v1/results.json", HERE / "build/original-freeze-v1/receipt.json"]
    evidence_paths += [HERE / "build" / name / "results.json" for name in
                       ("candidate-red-v1", "candidate-green-v1", "candidate-final-tests-v1",
                        "candidate-freeze-tests-v1", "original-regression-v1")]
    receipt = {"schema": 1, "status": "RAM_ONLY_NOT_FLASH_READY_FROZEN_OFFLINE",
               "board_tested": False, "flash_authorized": False, "saveenv": False,
               "artifacts": manifest["artifacts"], "inputs": manifest["inputs"], "rootfs": manifest["rootfs"],
               "source_snapshot": {str(p.relative_to(snapshot)): metadata(p) for p in sorted(snapshot.rglob("*")) if p.is_file()},
               "evidence": {str(p.relative_to(ROOT)): metadata(p) for p in evidence_paths},
               "candidate_tests": "43/43", "original_regression": "42/42", "independent_dtc": "10/10",
               "address_analysis": manifest["address_analysis"], "commands": commands,
               "not_covered": ["deployed SMDT U-Boot exact implementation", "actual bootm relocation and ARM64 entry",
                   "fresh destination environment and reserved spans", "RAM candidate execution", "early resource DT flash compatibility",
                   "USB recovery", "WiFi/PCM/MCU START"]}
    (target / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": metadata(target / "receipt.json"), "manifest": metadata(production / "manifest.json"),
                      "artifacts": manifest["artifacts"]}))


if __name__ == "__main__":
    main()
