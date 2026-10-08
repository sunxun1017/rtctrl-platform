#!/usr/bin/env python3
"""Compare complete Android device trees without operating hardware."""

import hashlib
import gzip
import importlib.util
import json
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "firstboot_audit",
    ROOT / "platforms/rk3568/boards/aiot-3568pq/verify-firstboot.py",
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def nodes(blob):
    header = struct.unpack_from(">10I", blob)
    position = header[2]
    end = position + header[9]
    stack = []
    found = set()
    while position < end:
        token = struct.unpack_from(">I", blob, position)[0]
        position += 4
        if token == 1:
            stop = blob.index(b"\0", position)
            stack.append(blob[position:stop].decode())
            found.add("/".join(stack) or "/")
            position = (stop + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length = struct.unpack_from(">I", blob, position)[0]
            position = (position + 8 + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            return found
        else:
            raise ValueError("Invalid DTB token")
    raise ValueError("Missing DTB end token")


def main():
    old = ROOT / "outputs/rk3568-backup-linux-20261003/extra/android-running.dtb"
    new = OUT / "baseline-v1/android-live.dtb"
    old_props, old_reserved = audit.read_dtb(old)
    new_props, new_reserved = audit.read_dtb(new)
    differences = []
    for key in sorted(old_props.keys() | new_props.keys()):
        if old_props.get(key) != new_props.get(key):
            differences.append({
                "path": key,
                "old_bytes": len(old_props[key]) if key in old_props else None,
                "new_bytes": len(new_props[key]) if key in new_props else None,
            })
    old_nodes, new_nodes = nodes(old.read_bytes()), nodes(new.read_bytes())
    result = {
        "old_file": str(old.relative_to(ROOT)),
        "new_file": str(new.relative_to(ROOT)),
        "old_sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
        "new_sha256": hashlib.sha256(new.read_bytes()).hexdigest(),
        "old_nodes": len(old_nodes),
        "new_nodes": len(new_nodes),
        "old_properties": len(old_props),
        "new_properties": len(new_props),
        "added_nodes": sorted(new_nodes - old_nodes),
        "removed_nodes": sorted(old_nodes - new_nodes),
        "reservations_equal": old_reserved == new_reserved,
        "property_differences": differences,
        "all_other_properties_equal": True,
        "new_kernel_boot_verified": False,
        "physical_peripheral_functions_verified": False,
    }
    def bootargs(props):
        return {
            token.split("=", 1)[0]: token
            for token in props["/chosen/bootargs"].rstrip(b"\0").decode().split()
        }

    old_args, new_args = bootargs(old_props), bootargs(new_props)
    result["bootarg_changed_keys"] = sorted(
        key for key in old_args.keys() | new_args.keys()
        if old_args.get(key) != new_args.get(key)
    )
    backups = json.loads((OUT / "backups-v1/receipt.json").read_text())
    old_manifest = json.loads((ROOT / "outputs/rk3568-backup-linux-20261003/manifest.json").read_text())
    downloaded = {
        entry["name"]: entry for entry in backups["entries"]
        if "remote_before_local_after_match" in entry
    }
    expected_names = {
        name + ".img" for name in
        ("boot", "recovery", "dtbo", "uboot", "trust", "vbmeta", "baseparameter", "misc")
    }
    download_entries = [
        entry for entry in backups["entries"] if "remote_before_local_after_match" in entry
    ]
    if len(download_entries) != 8 or set(downloaded) != expected_names:
        raise ValueError("Eight unique partition backups are required")
    for name, entry in downloaded.items():
        data = (OUT / "backups-v1" / name).read_bytes()
        if entry["remote"] != "/dev/block/by-name/" + name.removesuffix(".img"):
            raise ValueError("Unexpected partition identity: " + name)
        if entry["remote_before_local_after_match"] is not True:
            raise ValueError("Unverified backup: " + name)
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("Local backup changed: " + name)
    comparisons = []
    for partition in ("boot", "dtbo", "uboot", "trust", "vbmeta", "baseparameter", "misc"):
        name = partition + ".img"
        original = next(entry for entry in old_manifest["artifacts"] if Path(entry["file"]).name == name)
        current = downloaded[name]
        digest = hashlib.sha256((OUT / "backups-v1" / name).read_bytes()).hexdigest()
        if digest != current["sha256"]:
            raise ValueError("Local backup changed: " + name)
        comparisons.append({
            "partition": partition,
            "bytes": current["bytes"],
            "sha256": digest,
            "old_original_equal": digest == original["sha256"] and current["bytes"] == original["bytes"],
        })
    result["original_partition_comparison"] = comparisons
    result["backed_up_partitions"] = sorted(downloaded)
    result["local_full_backups_reverified"] = len(downloaded)
    result["backed_up_bytes"] = sum(entry["bytes"] for entry in downloaded.values())
    config_blob = (OUT / "baseline-v1/kernel.config.gz").read_bytes()
    config = gzip.decompress(config_blob).decode()
    result["android_config_sha256"] = hashlib.sha256(config_blob).hexdigest()
    result["android_kexec_enabled"] = "CONFIG_KEXEC=y" in config.splitlines()
    runtime = json.loads((OUT / "runtime-v1/receipt.json").read_text())
    result["static_userland_verified"] = runtime["completed"]
    result["protected_partitions_unchanged"] = runtime["protected_partitions_unchanged"]
    candidate = ROOT / "outputs/rk3568-audio-runtime-20261005/offline-next-delivery-v1/package-v1"
    selected = []
    for name in ("boot-padded.img", "runtime/snd-soc-rk817.ko"):
        data = (candidate / name).read_bytes()
        selected.append({
            "file": str((candidate / name).relative_to(ROOT)),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "crc32": format(zlib.crc32(data) & 0xffffffff, "08x"),
            "tested_on_new_board": False,
        })
    result["existing_linux_candidate"] = selected
    result["serial_recovery_connected"] = False
    result["full_linux_migration_completed"] = False
    (OUT / "fdt-comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
