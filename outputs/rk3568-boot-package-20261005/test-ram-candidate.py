#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise real candidate bytes, public entry points, and policy rejection."""
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
CMDLINE = "console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init ro loglevel=7 panic=0"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixed_id(data):
    data = bytearray(data)
    page = struct.unpack_from("<I", data, 36)[0]
    sizes = [struct.unpack_from("<I", data, offset)[0] for offset in (8, 16, 24, 1648)]
    sha = hashlib.sha1()
    position = page
    for index, size in enumerate(sizes):
        if index == 3:
            sha.update(struct.pack("<I", 0))
        sha.update(data[position:position + size])
        sha.update(struct.pack("<I", size))
        position = (position + size + page - 1) & ~(page - 1)
    data[576:608] = sha.digest() + bytes(12)
    return bytes(data)


def reject(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Invalid candidate was accepted")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).absolute()
    assert out == out.resolve() and out.is_relative_to(HERE / "build")
    out.mkdir(parents=True, exist_ok=False)
    cases = []
    candidate = out / "candidate"

    def run(name, call):
        try:
            call()
            cases.append({"name": name, "passed": True})
        except Exception as error:
            cases.append({"name": name, "passed": False, "error": type(error).__name__ + ": " + str(error)})

    def build():
        result = subprocess.run([sys.executable, "-B", str(HERE / "build-ram-candidate.py"),
                                 "--out", str(candidate)], capture_output=True, timeout=120)
        (out / "build.stdout").write_bytes(result.stdout)
        (out / "build.stderr").write_bytes(result.stderr)
        assert result.returncode == 0

    run("real-official-builder-cli", build)

    def bytes_():
        return (candidate / "boot-padded.img").read_bytes()

    def parse():
        return load("audit-ram-candidate.py").inspect_candidate(bytes_())

    def locked_inputs():
        report = parse()
        assert [(x["bytes"], x["sha256"]) for x in report["components"] if x["name"] in ("kernel", "ramdisk", "dtb")] == [
            (34755072, "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457"),
            (972203, "54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef"),
            (162414, "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1")]

    def preserved_resources():
        report = parse()
        old = load("audit-boot.py").inspect_boot((ROOT / "outputs/rk3568-backup-linux-20261003/original/boot.img").read_bytes())
        entries = report["resource"]["entries"]
        assert [e["path"] for e in entries] == [e["path"] for e in old["resource"]["entries"]]
        assert len(entries) == 11
        assert all(e["sha256"] == "7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1" for e in entries[:9])
        assert [(e["sha256"], e["bytes"]) for e in entries[9:]] == [(e["sha256"], e["bytes"]) for e in old["resource"]["entries"][9:]]
        assert all(e["sha1"] == e["stored_sha1"] for e in entries)
        assert all(e["offset"] % 512 == 0 for e in entries)

    def layout():
        report = parse()
        data = bytes_()
        assert len(data) == 41943040
        assert report["raw_bytes"] == 40478720
        assert [(e["name"], e["offset"], e["bytes"]) for e in report["components"]] == [
            ("kernel", 2048, 34755072), ("ramdisk", 34758656, 972203),
            ("second", 35731456, 4582400), ("dtb", 40314880, 162414)]
        assert data == fixed_id(data)
        assert not any(data[report["raw_bytes"]:])
        assert len(report["concatenated_dtbs"]) == 1
        assert report["header"]["cmdline"] == CMDLINE
        assert [report["header"][name] for name in ("kernel_addr", "ramdisk_addr", "second_addr", "tags_addr", "dtb_addr")] == [
            0x10008000, 0x11000000, 0x10f00000, 0x10000100, 0x11f00000]

    def safety():
        manifest = json.loads((candidate / "manifest.json").read_text())
        assert manifest["status"] == "RAM_ONLY_NOT_FLASH_READY"
        assert manifest["board_tested"] is False and manifest["flash_authorized"] is False
        addresses = manifest["address_analysis"]
        assert addresses["package_interval"] == [0x20000000, 0x22800000]
        assert addresses["image_header"]["image_size"] == 35389440
        assert addresses["actual_destinations_verified"] is False
        assert addresses["header_destination_overlaps"]
        assert manifest["rootfs"]["board_path"] == "/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4"

    run("literal-locked-input-sha-and-size", locked_inputs)
    run("original-11-names-two-logos-nine-uart-sha1", preserved_resources)
    run("literal-layout-id-complete-zero-tail", layout)
    run("ram-only-address-limitations", safety)

    def overwrite():
        before = hashlib.sha256(bytes_()).hexdigest()
        result = subprocess.run([sys.executable, "-B", str(HERE / "build-ram-candidate.py"),
                                 "--out", str(candidate)], capture_output=True, timeout=60)
        assert result.returncode != 0 and hashlib.sha256(bytes_()).hexdigest() == before

    def output_symlink():
        assert candidate.is_dir()
        link = out / "alias"
        link.symlink_to(candidate, target_is_directory=True)
        result = subprocess.run([sys.executable, "-B", str(HERE / "build-ram-candidate.py"),
                                 "--out", str(link / "forbidden")], capture_output=True, timeout=60)
        assert result.returncode != 0 and not (candidate / "forbidden").exists()

    def audit_cli():
        result = subprocess.run([sys.executable, "-B", str(HERE / "audit-ram-candidate.py"),
                                 "--package", str(candidate / "boot-padded.img"), "--out", str(out / "audit-cli")],
                                capture_output=True, timeout=60)
        assert result.returncode == 0
        result = subprocess.run([sys.executable, "-B", str(HERE / "audit-boot.py"),
                                 "--package", str(candidate / "boot-padded.img"), "--out", str(out / "not-original")],
                                capture_output=True, timeout=60)
        assert result.returncode != 0 and not (out / "not-original").exists()

    run("refuse-output-overwrite", overwrite)
    run("refuse-output-symlink", output_symlink)
    run("candidate-cli-explicit-original-mode-reject", audit_cli)

    def malformed_input_lock():
        common = load("build-roundtrip.py")
        path = out / "changed-input"
        path.write_bytes(b"1234")
        reject(lambda: common.read_locked(path, 4, hashlib.sha256(b"4321").hexdigest()))
        link = out / "input-link"
        link.symlink_to(path)
        reject(lambda: common.read_locked(link, 4, hashlib.sha256(b"1234").hexdigest()))

    def wrong_source():
        path = out / "wrong-official.py"
        path.write_bytes(b"raise AssertionError('must not run')\n")
        reject(lambda: load("build-roundtrip.py").official_module(path))

    def address_span():
        builder = load("build-ram-candidate.py")
        kernel = (candidate / "components/kernel").read_bytes()
        report = parse()
        sizes = {e["name"]: e["bytes"] for e in report["components"]}
        for offset, value in ((8, 1), (16, 34755072)):
            bad_image = bytearray(kernel)
            struct.pack_into("<Q", bad_image, offset, value)
            reject(lambda: builder.address_analysis(bytes(bad_image), report["header"], sizes))
        altered = dict(report["header"], kernel_addr=0x20000000)
        reject(lambda: builder.address_analysis(kernel, altered, sizes))

    def valid_fdt_wrong_lock(resource):
        data = bytearray(bytes_())
        uart = (candidate / "components/dtb").read_bytes()
        place = uart.index(b"rockchip")
        if resource:
            start = 35731456 + 6144
        else:
            start = 40314880
        data[start + place:start + place + 8] = b"rockchop"
        changed = bytes(data[start:start + len(uart)])
        load("audit-boot.py").inspect_fdt(changed)
        if resource:
            data[35731456 + 736:35731456 + 756] = hashlib.sha1(changed).digest()
        data = fixed_id(data)
        load("audit-boot.py").inspect_boot(data, expected_concat_count=1)
        reject(lambda: load("audit-ram-candidate.py").inspect_candidate(data))

    run("real-input-sha-and-symlink-rejection", malformed_input_lock)
    run("official-source-rejected-before-execution", wrong_source)
    run("image-memory-header-and-package-overlap-rejection", address_span)
    run("valid-resource-fdt-id-and-sha-but-wrong-uart", lambda: valid_fdt_wrong_lock(True))
    run("valid-v2-fdt-and-id-but-wrong-uart", lambda: valid_fdt_wrong_lock(False))

    def bad(offset, replacement, rehash=False, rsce_entry=None):
        data = bytearray(bytes_())
        data[offset:offset + len(replacement)] = replacement
        if rsce_entry is not None:
            table = 35731456 + 512 * (1 + rsce_entry)
            blocks, size = struct.unpack_from("<II", data, table + 260)
            payload = data[35731456 + blocks * 512:35731456 + blocks * 512 + size]
            data[table + 224:table + 244] = hashlib.sha1(payload).digest()
        if rehash:
            data = fixed_id(data)
        reject(lambda: load("audit-ram-candidate.py").inspect_candidate(bytes(data)))

    for name, offset, replacement, rehash, entry in [
        ("magic", 0, b"BADBOOT!", False, None),
        ("version", 40, struct.pack("<I", 1), False, None),
        ("header-size", 1644, struct.pack("<I", 1659), False, None),
        ("page", 36, struct.pack("<I", 1024), False, None),
        ("kernel-bounds", 8, struct.pack("<I", 0xffffffff), False, None),
        ("id", 576, bytes(20), False, None),
        ("id-padding", 607, b"x", False, None),
        ("header-padding", 1700, b"x", False, None),
        ("kernel-padding", 34757120, b"x", False, None),
        ("ramdisk-padding", 35730859, b"x", False, None),
        ("dtb-padding", 40477294, b"x", False, None),
        ("partition-tail", 41943039, b"x", False, None),
        ("wrong-locked-kernel-valid-id", 2048, b"WRONG", True, None),
        ("wrong-locked-initrd-valid-id", 34758656, b"WRONG", True, None),
        ("wrong-cmdline", 64, b"badconsole", False, None),
        ("wrong-kernel-address", 12, struct.pack("<I", 0x400000), False, None),
        ("wrong-dtb-address", 1652, struct.pack("<Q", 0x3000000), False, None),
        ("resource-tag-valid-id", 35731456, b"ABCD", True, None),
        ("resource-count-valid-id", 35731456 + 12, struct.pack("<I", 10), True, None),
        ("resource-name-valid-id", 35731456 + 516, b"evil", True, None),
        ("resource-sha-valid-id", 35731456 + 736, bytes(20), True, None),
        ("resource-table-offset-valid-id", 35731456 + 772, struct.pack("<I", 1), True, None),
        ("resource-tail-padding-valid-id", 40313800, b"x", True, None),
        ("wrong-logo-valid-two-hashes", 35731456 + 1471488 + 100, b"evil", True, 9),
        ("wrong-uart-valid-two-hashes", 35731456 + 6144 + 100, b"evil", True, 0),
        ("v2-dtb-magic-valid-id", 40314880, b"BAD!", True, None),
        ("v2-dtb-total-valid-id", 40314884, struct.pack(">I", 40), True, None),
    ]:
        run("reject-" + name, lambda o=offset, p=replacement, h=rehash, e=entry: bad(o, p, h, e))
    run("reject-truncated-package", lambda: reject(lambda: load("audit-ram-candidate.py").inspect_candidate(bytes_()[:-1])))
    run("reject-extra-package-tail", lambda: reject(lambda: load("audit-ram-candidate.py").inspect_candidate(bytes_() + b"\0")))
    run("reject-empty-package", lambda: reject(lambda: load("audit-ram-candidate.py").inspect_candidate(b"")))
    report = {"total": len(cases), "passed": sum(e["passed"] for e in cases), "cases": cases,
              "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "source_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                                for name in ("audit-boot.py", "build-ram-candidate.py", "audit-ram-candidate.py") if (HERE / name).exists()},
              "board_tested": False}
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"total": report["total"], "passed": report["passed"]}))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
