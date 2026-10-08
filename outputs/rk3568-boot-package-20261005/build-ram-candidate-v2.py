#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build only the fixed UART/native-PID1-v3 RAM experiment, never a flash image."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
INPUTS = {
    "kernel": ("outputs/rk3568-rcu-reset-20261004/Image", 34755072,
               "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457"),
    "ramdisk": ("outputs/rk3568-pid1-20261005/build/production-v3/initramfs-pid1.cpio.gz", 972203,
                "54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef"),
    "dtb": ("outputs/rk3568-boot-package-20261005/build/uart-shim-v2/uart-ram-shim.dtb", 162457,
            "75c43a4b217f10dbbbc8ca953124f33e3e548f8fa9994d3c70cde8743261f582")}
ROOTFS = "outputs/rk3568-pid1-20261005/build/production-v3/rootfs-pid1.ext4"
ROOTFS_SHA = "3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d"
CMDLINE = "console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init ro loglevel=7 panic=0"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_resource(original, audit, uart):
    entries = audit["resource"]["entries"]
    second = audit["components"][2]
    old = original[second["offset"]:second["offset"] + second["bytes"]]
    result = bytearray(512 * (1 + len(entries)))
    struct.pack_into("<4sHHBBBBI", result, 0, b"RSCE", 0, 0, 1, 1, 1, 0, len(entries))
    for entry in entries:
        payload = uart if entry["path"].endswith(".dtb") else old[entry["offset"]:entry["offset"] + entry["bytes"]]
        table = 512 * (1 + entry["index"])
        result[table:table + 4] = b"ENTR"
        name = entry["path"].encode("ascii")
        result[table + 4:table + 4 + len(name)] = name
        result[table + 224:table + 244] = hashlib.sha1(payload).digest()
        struct.pack_into("<III", result, table + 256, 20, len(result) // 512, len(payload))
        result.extend(payload)
        result.extend(bytes((-len(result)) % 512))
    return bytes(result)


def overlap(spans):
    pairs = []
    for index, (name, start, end) in enumerate(spans):
        for other, left, right in spans[index + 1:]:
            if max(start, left) < min(end, right):
                pairs.append({"left": name, "right": other, "intersection": [max(start, left), min(end, right)]})
    return pairs


def address_analysis(kernel, header, sizes):
    if kernel[56:60] != b"ARMd":
        raise ValueError("ARM64 Image magic mismatch")
    text_offset, image_size, flags = struct.unpack_from("<QQQ", kernel, 8)
    if text_offset != 0 or image_size != 35389440 or image_size < len(kernel):
        raise ValueError("Unexpected ARM64 Image memory header")
    package = [0x20000000, 0x22800000]
    header_spans = [(name, header[name + "_addr"], header[name + "_addr"] +
                     (image_size if name == "kernel" else sizes[name]))
                    for name in ("kernel", "ramdisk", "second", "dtb")]
    if overlap([("package", *package)] + header_spans) != overlap(header_spans):
        raise ValueError("Tentative package overlaps header component destinations")
    return {"package_addr_status": "TENTATIVE_ROOT_AGENT_SELECTED_RECHECK_BEFORE_EXECUTION",
            "package_interval": package, "package_bytes": 41943040,
            "image_header": {"text_offset": text_offset, "image_size": image_size, "flags": flags},
            "tested_booti_kernel_interval_at_400000": [0x400000, 0x400000 + image_size],
            "header_destination_intervals": {name: [start, end] for name, start, end in header_spans},
            "header_destination_overlaps": overlap(header_spans),
            "package_overlaps_header_destinations": False,
            "header_addresses_are_actual_destinations": False,
            "actual_destinations_verified": False,
            "historical_env_only": {"kernel_addr_r": 0x280000, "fdt_addr_r": 0xa100000, "ramdisk_addr_r": 0xa200000},
            "reported_fresh_bank_interval": [0x09400000, 0xf0000000],
            "tentative_package_inside_reported_bank": 0x09400000 <= package[0] < package[1] <= 0xf0000000,
            "relocation_reserved_memory_and_environment_recheck_required": True,
            "arm64_entry_and_uboot_actual_move_rules_recheck_required": True}


def build(out):
    common = load("build-roundtrip.py")
    audit_module = load("audit-boot.py")
    policy = load("audit-ram-candidate-v2.py")
    out = Path(out).absolute()
    if out != out.resolve() or not out.is_relative_to(HERE / "build"):
        raise ValueError("Need new ordinary output path inside own build")
    original = common.read_locked(common.BOOT, common.BOOT_SIZE, common.BOOT_SHA)
    official = common.official_module(HERE / "sources/mkbootimg.py")
    original_audit = audit_module.inspect_boot(original)
    data = {name: common.read_locked(ROOT / path, size, sha) for name, (path, size, sha) in INPUTS.items()}
    rootfs = common.read_locked(ROOT / ROOTFS, 16777216, ROOTFS_SHA)
    data["second"] = build_resource(original, original_audit, data["dtb"])
    header = original_audit["header"]
    addresses = address_analysis(data["kernel"], header, {name: len(payload) for name, payload in data.items()})
    nominal = [("kernel", 0x400000, 0x400000 + addresses["image_header"]["image_size"]),
               ("dt_shim_and_overlay_result", 0x3000000, 0x3000000 + 162538),
               ("initrd", 0x4000000, 0x4000000 + len(data["ramdisk"])),
               ("package", *addresses["package_interval"])]
    if overlap(nominal):
        raise ValueError("Root temporary nominal destinations overlap")
    addresses["root_temporary_nominal_blob_intervals"] = {name: [start, end] for name, start, end in nominal}
    addresses["root_temporary_nominal_overlaps"] = []
    addresses["dt_workspace_growth_and_reserved_spans_still_require_live_check"] = True
    out.mkdir(parents=True, exist_ok=False)
    components = out / "components"
    components.mkdir()
    for name, payload in data.items():
        common.write_new(components / name, payload)
    with ExitStack() as stack:
        output = stack.enter_context((out / "boot-raw.img").open("xb"))
        files = {name: stack.enter_context((components / name).open("rb")) for name in data}
        args = SimpleNamespace(output=output, **files, recovery_dtbo=None, header_version=2, pagesize=2048,
                               base=0, kernel_offset=header["kernel_addr"], ramdisk_offset=header["ramdisk_addr"],
                               second_offset=header["second_addr"], tags_offset=header["tags_addr"],
                               dtb_offset=header["dtb_addr"], os_version=header["os_version"],
                               os_patch_level=header["os_patch_level"], board=header["board"], cmdline=CMDLINE)
        official.write_header(args)
        official.write_data(args, args.pagesize)
    raw = (out / "boot-raw.img").read_bytes()
    if len(raw) > 41943040:
        raise ValueError("Candidate exceeds 40 MiB")
    padded = raw + bytes(41943040 - len(raw))
    report = policy.inspect_candidate(padded)
    common.write_new(out / "boot-padded.img", padded)
    common.write_new(out / "audit.json", (json.dumps(report, indent=2) + "\n").encode())
    exports = out / "rsce"
    exports.mkdir()
    for entry in report["resource"]["entries"]:
        target = exports / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        common.write_new(target, data["second"][entry["offset"]:entry["offset"] + entry["bytes"]])
    dtbs = out / "dtb-concat"
    dtbs.mkdir()
    common.write_new(dtbs / "00.dtb", data["dtb"])
    source_dir = out / "source-inputs"
    source_dir.mkdir()
    for name in ("build-ram-candidate-v2.py", "audit-ram-candidate-v2.py", "audit-boot.py", "build-roundtrip.py",
                 "test-ram-candidate-v2.py", "PLAN-v2.md", "README-v2.md", "DT-PLAN.md", "source-lock-v2.json",
                 "build-uart-shim-v2.py", "dt-semantics-v2.py", "libfdt-v2.py"):
        common.write_new(source_dir / name, (HERE / name).read_bytes())
    common.write_new(source_dir / "mkbootimg.py", common.read_locked(HERE / "sources/mkbootimg.py", common.OFFICIAL_SIZE, common.OFFICIAL_SHA))
    manifest = {"schema": 1, "status": "RAM_ONLY_NOT_FLASH_READY", "board_tested": False,
                "ram_candidate_version": 2, "packaged_dtb_is_pre_overlay_shim": True,
                "real_overlay": report["real_overlay"], "original_dtbo": report["original_dtbo"],
                "shim_manifest": {"path": "outputs/rk3568-boot-package-20261005/build/uart-shim-v2/manifest.json",
                    **common.metadata((HERE / "build/uart-shim-v2/manifest.json").read_bytes())},
                "flash_authorized": False, "saveenv": False, "usb_recovery_confirmed": False,
                "official_commit": common.COMMIT, "official_source_sha256": common.OFFICIAL_SHA,
                "official_functions": ["write_header", "write_data"],
                "original_unchanged": common.metadata(original),
                "original_freeze_receipt": {"path": "outputs/rk3568-boot-package-20261005/build/original-freeze-v1/receipt.json",
                    **common.metadata((HERE / "build/original-freeze-v1/receipt.json").read_bytes())},
                "artifacts": {"boot-raw.img": common.metadata(raw), "boot-padded.img": common.metadata(padded)},
                "inputs": {name: {"path": path, **common.metadata(data[name])} for name, (path, _, _) in INPUTS.items()},
                "rootfs": {"path": ROOTFS, "board_path": "/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4", **common.metadata(rootfs)},
                "rsce_policy": "ALL_ORIGINAL_NAMES_AND_LOGOS_NINE_IDENTICAL_UART_DTBS",
                "v2_dtb_policy": "ONE_IDENTICAL_UART_DTB", "cmdline": CMDLINE,
                "address_analysis": addresses, "boot_invocation": "bootm PACKAGE_ADDR", "boot_command_arity": 1,
                "root_agent_temporary_destination_plan": {"kernel_addr_r": 0x400000, "fdt_addr_r": 0x3000000,
                    "ramdisk_addr_r": 0x4000000, "package_addr": 0x20000000,
                    "actual_environment_rechecked_on_board": False},
                "source_inputs": {path.name: common.metadata(path.read_bytes()) for path in sorted(source_dir.iterdir())},
                "early_uboot_dtb": "UNCHANGED_EMMC_ORIGINAL_BOOT_RESOURCE_FOR_RAM_ONLY",
                "deployed_smdt_uboot_exact_source_known": False,
                "required_before_ram_execution": ["fresh bdinfo and reserved ranges", "fresh env destination addresses",
                    "actual relocation spans and ARM64 entry", "full 41943040 byte SHA/CRC", "root agent explicit execution"]}
    common.write_new(out / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print(json.dumps({"status": manifest["status"], "artifacts": manifest["artifacts"], "board_tested": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        build(args.out)
    except (OSError, ValueError) as error:
        parser.exit(1, "RAM_CANDIDATE_BUILD_REJECTED: " + str(error) + "\n")


if __name__ == "__main__":
    main()
