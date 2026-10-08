#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Strict approved v2 RAM candidate policy, separate from original-package mode."""
import argparse
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CMDLINE = "console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init ro loglevel=7 panic=0"
EXPECTED = {
    "kernel": (34755072, "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457"),
    "ramdisk": (972203, "54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef"),
    "dtb": (162457, "75c43a4b217f10dbbbc8ca953124f33e3e548f8fa9994d3c70cde8743261f582")}


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def original():
    common = load("build-roundtrip.py")
    data = common.read_locked(common.BOOT, common.BOOT_SIZE, common.BOOT_SHA)
    return load("audit-boot.py").inspect_boot(data)


def inspect_candidate(data):
    audit = load("audit-boot.py")
    audit.require(len(data) == 41943040, "candidate must be complete 40 MiB")
    report = audit.inspect_boot(data, expected_concat_count=1)
    audit.require(report["raw_bytes"] == 40478720, "candidate raw layout mismatch")
    for component in report["components"]:
        if component["name"] in EXPECTED:
            audit.require((component["bytes"], component["sha256"]) == EXPECTED[component["name"]],
                          "candidate locked " + component["name"] + " mismatch")
    reference = original()
    header = report["header"]
    for name in ("version", "header_size", "page_size", "kernel_addr", "ramdisk_addr", "second_addr",
                 "tags_addr", "dtb_addr", "os_version_encoded", "board"):
        audit.require(header[name] == reference["header"][name], "candidate header metadata mismatch: " + name)
    audit.require(header["cmdline"] == CMDLINE, "candidate fixed Linux cmdline mismatch")
    entries = report["resource"]["entries"]
    old = reference["resource"]["entries"]
    audit.require([e["path"] for e in entries] == [e["path"] for e in old], "candidate RSCE names/order mismatch")
    expected_offset = 12 * 512
    for entry, prior in zip(entries, old):
        audit.require(entry["offset"] == expected_offset, "candidate RSCE noncanonical offset")
        expected_offset += (entry["bytes"] + 511) & ~511
        if entry["path"].endswith(".dtb"):
            audit.require((entry["bytes"], entry["sha256"]) == EXPECTED["dtb"], "candidate RSCE locked UART mismatch")
        else:
            audit.require((entry["bytes"], entry["sha256"]) == (prior["bytes"], prior["sha256"]),
                          "candidate original logo mismatch")
    audit.require(report["components"][2]["bytes"] == expected_offset == 4582400,
                  "candidate RSCE exact extent mismatch")
    common = load("build-roundtrip.py")
    shim_builder = load("build-uart-shim-v2.py")
    bridge = load("libfdt-v2.py")
    uart = common.read_locked(ROOT / "outputs/rk3568-motor-alignment-20261004/uart.dtb", 162414,
        "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1")
    dtbo = common.read_locked(ROOT / "outputs/rk3568-backup-linux-20261003/original/dtbo.img", 4194304,
        "59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d")
    dt = report["components"][3]
    packaged_shim = data[dt["offset"]:dt["offset"] + dt["bytes"]]
    semantic = load("dt-semantics-v2.py")
    audit.require(semantic.diff(semantic.parse(uart), semantic.parse(packaged_shim)) == semantic.SHIM_DIFF,
                  "Packaged shim is not exactly two prerequisites")
    apply_report, applied = bridge.RealLibFdt().apply(packaged_shim, shim_builder.overlay_entry(dtbo))
    audit.require(apply_report["status"] == 0 and applied is not None, "Packaged DT real overlay failed")
    difference = shim_builder.validate_transition(uart, applied)
    report.update({"mode": "RAM_ONLY_NOT_FLASH_READY", "flash_authorized": False,
                   "actual_ram_loading_not_verified": True, "ram_candidate_version": 2,
                   "packaged_dtb_is_pre_overlay_shim": True, "original_dtbo": common.metadata(dtbo),
                   "real_overlay": {"libfdt_sha256": bridge.LIB_SHA, "apply": apply_report,
                                    "full_semantic_diff": difference, "applied_audit_only": common.metadata(applied)}})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    audit = load("audit-boot.py")
    report = inspect_candidate(audit.read_ordinary(args.package))
    out = Path(args.out).absolute()
    audit.require(out == out.resolve() and out.is_relative_to(HERE / "build"), "Need ordinary fresh evidence path")
    out.mkdir(parents=True, exist_ok=False)
    report["candidate_auditor_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "RAM_CANDIDATE_OFFLINE_VERIFIED", "package": report["package"],
                      "raw_bytes": report["raw_bytes"], "flash_authorized": False, "board_tested": False}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit("RAM_CANDIDATE_REJECTED: " + str(error))
