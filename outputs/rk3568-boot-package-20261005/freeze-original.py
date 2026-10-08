#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Seal the original package evidence before any RAM-candidate extension."""
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
    lock = json.loads((HERE / "source-lock.json").read_text())
    tag = HERE / "sources/android-11.0.0_r1.json"
    record = json.loads(tag.read_text().split("\n", 1)[1])
    assert record["commit"] == "99894068024224a62595e051d69e748e2499f52e"
    lock["tag_resolution"] = {"file": str(tag.relative_to(HERE)), **metadata(tag),
        "url": "https://android.googlesource.com/platform/system/tools/mkbootimg/+/refs/tags/android-11.0.0_r1?format=JSON",
        "commit": record["commit"], "tree": record["tree"]}
    reference = HERE / "sources/rockchip-reference-v1"
    commit = "1c535d65b8509f388d09e49fb6961f49fda35a1d"
    assert json.loads((reference / "commit.json").read_text())["sha"] == commit
    paths = {"image-android.c": "common/image-android.c",
             "resource_img.c": "arch/arm/mach-rockchip/resource_img.c",
             "boot_rkimg.c": "arch/arm/mach-rockchip/boot_rkimg.c"}
    lock["public_uboot_reference"] = {"commit": commit,
        "is_exact_deployed_smdt_implementation": False,
        "provenance": {"file": str((reference / "commit.json").relative_to(HERE)),
                       **metadata(reference / "commit.json")},
        "files": [{"file": str((reference / name).relative_to(HERE)),
                   **metadata(reference / name), "license": "GPL-2.0-or-later",
                   "url": "https://raw.githubusercontent.com/rockchip-linux/u-boot/" + commit + "/" + path}
                  for name, path in paths.items()]}
    license_files = []
    for name in ("Apache-2.0", "GPL-2"):
        target = HERE / "sources" / (name + ".txt")
        with target.open("xb") as output:
            output.write((Path("/usr/share/common-licenses") / name).read_bytes())
        license_files.append({"file": str(target.relative_to(HERE)), **metadata(target)})
    lock["license_texts"] = license_files
    (HERE / "source-lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    canonical = HERE / "build/roundtrip-v1"
    commands = [
        [sys.executable, "-B", str(HERE / "build-roundtrip.py"), "--out", str(canonical)],
        [sys.executable, "-B", str(HERE / "audit-boot.py"), "--package", str(canonical / "boot-padded.img"),
         "--out", str(HERE / "build/independent-original-v1")],
        [sys.executable, "-B", str(HERE / "crosscheck-dt.py"), "--roundtrip", str(canonical),
         "--out", str(HERE / "build/dtc-original-v1")]]
    for command in commands:
        subprocess.run(command, check=True, timeout=180)
    for directory, total, passed in (("red-v1", 42, 0), ("audit-green-v1", 39, 39),
                                     ("roundtrip-red-v1", 42, 39), ("roundtrip-green-v1", 42, 42)):
        evidence = json.loads((HERE / "build" / directory / "results.json").read_text())
        assert evidence["total"] == total and evidence["passed"] == passed
    target = HERE / "build/original-freeze-v1"
    target.mkdir(exist_ok=False)
    snapshot = target / "source-snapshot"
    snapshot.mkdir()
    for source in HERE.iterdir():
        if source.is_file():
            shutil.copyfile(source, snapshot / source.name)
    shutil.copytree(HERE / "sources", snapshot / "sources")
    audit = json.loads((canonical / "audit.json").read_text())
    ram = {"schema": 1, "kind": "ORIGINAL_BACKUP_RAM_ONLY",
           "package_path": str((canonical / "boot-padded.img").relative_to(ROOT)),
           **audit["package"], "raw_bytes": audit["raw_bytes"],
           "partition_tail_bytes": audit["partition_tail_bytes"],
           "invocation": "bootm PACKAGE_ADDR", "command_arity": 1,
           "package_addr_chosen_on_board": False, "board_tested": False,
           "header_addresses_are_not_loading_plan": True,
           "fresh_bdinfo_and_reserved_ranges_required": True, "flash": False, "saveenv": False}
    (target / "original-ram-manifest-v1.json").write_text(json.dumps(ram, indent=2) + "\n")
    sources = {str(p.relative_to(snapshot)): metadata(p) for p in sorted(snapshot.rglob("*")) if p.is_file()}
    evidence_paths = [canonical / "manifest.json", canonical / "audit.json",
                      HERE / "build/independent-original-v1/audit.json",
                      HERE / "build/dtc-original-v1/results.json"]
    evidence_paths += [HERE / "build" / name / "results.json" for name in
                       ("red-v1", "audit-green-v1", "roundtrip-red-v1", "roundtrip-green-v1")]
    receipt = {"schema": 1, "status": "ORIGINAL_ROUNDTRIP_FROZEN_OFFLINE",
               "original_package": audit["package"], "original_unchanged": True,
               "canonical_artifacts": json.loads((canonical / "manifest.json").read_text())["artifacts"],
               "source_snapshot": sources, "evidence": {str(p.relative_to(ROOT)): metadata(p) for p in evidence_paths},
               "ram_manifest": metadata(target / "original-ram-manifest-v1.json"),
               "parser_tests": "39/39", "roundtrip_tests": "42/42", "independent_dtc": "20/20",
               "commands": commands, "board_tested": False, "flash_authorized": False}
    (target / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": metadata(target / "receipt.json"), "ram_manifest": receipt["ram_manifest"]}))


if __name__ == "__main__":
    main()
