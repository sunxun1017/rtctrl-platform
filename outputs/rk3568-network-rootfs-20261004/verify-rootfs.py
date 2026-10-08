#!/usr/bin/env python3
"""Audit the ordinary ext4 image read-only with e2fsprogs and execute static QEMU tests."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rootfs_builder", HERE / "build-rootfs.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def debugfs(image, command):
    result = builder.run(["debugfs", "-R", command, str(image)])
    errors = result.stderr.decode(errors="replace").splitlines()
    if any(line.strip() and not line.startswith("debugfs ") for line in errors):
        builder.fail("debugfs rejected command: " + command + "\n" + "\n".join(errors))
    return result.stdout


def inventory(image):
    entries = {}
    queue = ["/"]
    visited = set()
    while queue:
        directory = queue.pop()
        if directory in visited:
            builder.fail("Directory cycle in ext4 image")
        visited.add(directory)
        output = debugfs(image, "ls -p -l " + directory).decode()
        for line in output.splitlines():
            if not line.strip():
                continue
            fields = line.split("/")
            if len(fields) < 7 or not fields[1].isdigit():
                builder.fail("Unrecognized debugfs directory record: " + line)
            inode, mode, uid, gid, name = fields[1:6]
            if inode == "0" and mode == "000000" and uid == "0" and gid == "0" and not name:
                # Preallocated lost+found space is reported as empty inode-0 slots.
                continue
            if name in {".", ".."}:
                if directory == "/" and name == ".":
                    entries["/"] = {"inode": int(inode), "mode": int(mode, 8), "uid": int(uid), "gid": int(gid)}
                continue
            if not inode.isdigit() or "/" in name or not name:
                builder.fail("Unsafe directory record")
            path = directory.rstrip("/") + "/" + name
            if path in entries:
                builder.fail("Duplicate ext4 path")
            entries[path] = {"inode": int(inode), "mode": int(mode, 8), "uid": int(uid), "gid": int(gid)}
            if int(mode, 8) & 0o170000 == 0o040000:
                queue.append(path)
    return entries


def filesystem_info(image):
    output = builder.run(["dumpe2fs", "-h", str(image)], text=True).stdout
    values = {}
    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key] = value.strip()
    if values.get("Filesystem state") != "clean":
        builder.fail("Filesystem is not clean")
    features = values["Filesystem features"].split()
    if "64bit" in features or "metadata_csum" in features:
        builder.fail("Unexpected optional filesystem features")
    block_size = int(values["Block size"])
    block_count = int(values["Block count"])
    if block_size * block_count != builder.SIZE:
        builder.fail("Wrong filesystem capacity")
    return {
        "bytes": builder.SIZE,
        "block_size": block_size,
        "blocks": block_count,
        "free_blocks": int(values["Free blocks"]),
        "allocated_bytes": (block_count - int(values["Free blocks"])) * block_size,
        "filesystem_state": values["Filesystem state"],
        "features": features,
    }


def validate_entries(expected, actual):
    if set(expected) != set(actual):
        builder.fail("Image path inventory differs: " + str(sorted(set(expected) ^ set(actual))))
    types = {"directory": 0o040000, "file": 0o100000, "symlink": 0o120000}
    for name, entry in expected.items():
        observed = actual[name]
        if observed["uid"] != 0 or observed["gid"] != 0:
            builder.fail("Non-root inode ownership: " + name)
        if observed["mode"] != types[entry["type"]] | entry["mode"]:
            builder.fail("Wrong inode type/mode: " + name)
    inode_ids = [item["inode"] for item in actual.values()]
    if len(set(inode_ids)) != len(inode_ids):
        builder.fail("Unexpected hard-linked entries")


def qemu_checks(extracted, expected_applets):
    qemu = builder.bounded_path(builder.ROOT / builder.QEMU, builder.ROOT, regular=True)
    checks = {}
    commands = {
        "busybox_applets": [str(extracted / "bin/busybox"), "--list"],
        "wpa_supplicant_version": [str(extracted / "usr/bin/wpa_supplicant"), "-v"],
        "wpa_cli_version": [str(extracted / "usr/bin/wpa_cli"), "-v"],
        "codec_test": [str(extracted / "usr/bin/codec-test")],
        "pty_test": [str(extracted / "usr/bin/pty-test")],
    }
    for name, command in commands.items():
        result = builder.run([str(qemu)] + command, timeout=45)
        text = (result.stdout + result.stderr).decode(errors="replace")
        if name == "busybox_applets" and result.stdout.decode().splitlines() != expected_applets:
            builder.fail("Actual BusyBox applets do not match packaged links")
        if name.startswith("wpa_") and "v2.11" not in text:
            builder.fail("Wrong WPA version")
        checks[name] = {"exit_code": result.returncode, "output": text.strip()}
    result = subprocess.run([str(qemu), str(extracted / "usr/bin/network-helper")],
                            capture_output=True, timeout=10)
    if result.returncode != 2 or result.stdout or result.stderr:
        builder.fail("Helper did not execute its expected no-operation argument rejection")
    checks["helper_usage"] = {"exit_code": 2, "expected_usage_exit": True}
    return checks


def verify(output, execute=True):
    output = builder.bounded_path(output, HERE)
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(output)):
        builder.fail("Output path cannot contain debugfs command delimiters or whitespace")
    image = builder.bounded_path(output / "rootfs.img", HERE, regular=True)
    manifest_path = builder.bounded_path(output / "rootfs-manifest.json", HERE, regular=True)
    build_dir = builder.bounded_path(output / "build", HERE)
    manifest = json.loads(manifest_path.read_text())
    if image.stat().st_size != builder.SIZE:
        builder.fail("Image must be an ordinary 64 MiB file")
    if manifest["image"] != {"file": "rootfs.img", "bytes": builder.SIZE, "sha256": builder.sha(image.read_bytes())}:
        builder.fail("Image checksum differs from manifest")
    expected_specs, inputs = builder.specifications()
    expected = builder.manifest_entries(expected_specs)
    if manifest["entries"] != expected or manifest["inputs"] != inputs:
        builder.fail("Manifest content differs from fixed verified input whitelist")
    if manifest["sources"] != builder.source_inputs():
        builder.fail("Source provenance changed after packaging")
    expected_kernel = {"release": builder.RELEASE, "source_commit": builder.COMMIT,
                       "image_sha256": builder.IMAGE_SHA, "config_sha256": builder.CONFIG_SHA}
    if manifest["kernel"] != expected_kernel:
        builder.fail("Manifest kernel binding is incorrect")
    builder.read_input("outputs/rk3568-rcu-reset-20261004/Image", builder.IMAGE_SHA)
    builder.read_input("outputs/rk3568-rcu-reset-20261004/kernel.config", builder.CONFIG_SHA)
    if manifest["policy"] != {
        "pid1_in_image": False, "autostart": False, "switch_root_tested": False,
        "credentials_in_image": False, "tmp_must_be_bound_to_ram": True,
        "manufacturer_android_libraries_included": False,
        "physical_mcu_tool_included": False, "board_tested": False,
    }:
        builder.fail("Rootfs policy changed")
    if set(manifest["binary_dependencies"]) != set(builder.FIRMWARE):
        builder.fail("Unexpected binary dependency inventory")
    for name, expected_sha in builder.FIRMWARE.items():
        item = manifest["binary_dependencies"][name]
        if item != {"sha256": expected_sha, "role": "firmware_or_nvram_binary",
                    "corresponding_source_obtained": False, "redistribution_permission_verified": False,
                    "distribution_scope": "private_local_testing_only"}:
            builder.fail("Firmware provenance/permission must remain explicit")
    check = subprocess.run(["e2fsck", "-f", "-n", str(image)], capture_output=True, text=True, timeout=30)
    if check.returncode != 0:
        builder.fail("Read-only e2fsck failed: " + check.stdout + check.stderr)
    info = filesystem_info(image)
    observed = inventory(image)
    validate_entries(expected, observed)
    # Reserved/journal inodes are not directory entries. Check their ownership too.
    for inode in sorted({1, 2, 7, 8} | {item["inode"] for item in observed.values()}):
        text = debugfs(image, "stat <" + str(inode) + ">").decode()
        owner = re.search(r"User:\s*(\d+)\s+Group:\s*(\d+)", text)
        if owner is None or owner.groups() != ("0", "0"):
            builder.fail("Non-root or unreadable allocated/reserved inode: " + str(inode))
    with tempfile.TemporaryDirectory(prefix="audit-", dir=build_dir) as temporary:
        extracted = Path(temporary)
        for name, entry in expected.items():
            if entry["type"] == "file":
                target = extracted / name.lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                debugfs(image, "dump " + name + " " + str(target))
                data = target.read_bytes()
                if len(data) != entry["bytes"] or builder.sha(data) != entry["sha256"]:
                    builder.fail("Image payload differs: " + name)
                target.chmod(entry["mode"])
                if data.startswith(b"\x7fELF"):
                    builder.check_elf(data, module=name.endswith(".ko"))
            elif entry["type"] == "symlink":
                text = debugfs(image, "stat " + name).decode()
                link = re.search(r'Fast link dest: "(.*)"', text)
                if link is None or link.group(1) != entry["target"]:
                    builder.fail("Symlink target differs: " + name)
        qemu = qemu_checks(extracted, builder.applets()) if execute else {}
    return {
        "status": "HOST_ROOTFS_VERIFIED", "image_sha256": manifest["image"]["sha256"],
        "filesystem": info, "path_count": len(observed),
        "all_ordinary_and_reserved_inode_owners_root": True,
        "readonly_e2fsck_passed": True, "payload_and_symlink_inventory_matched": True,
        "static_aarch64_payloads_passed": True, "qemu": qemu,
        "board_tested": False, "init_or_switch_root_executed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.output_dir), indent=2))
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, "ROOTFS_VERIFY_REJECTED: " + str(error) + "\n")


if __name__ == "__main__":
    main()
