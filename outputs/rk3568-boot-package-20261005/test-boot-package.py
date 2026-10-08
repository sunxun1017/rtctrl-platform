#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real original bytes and bounded mutations exercise offline package tools."""
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
BOOT = ROOT / "outputs/rk3568-backup-linux-20261003/original/boot.img"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(name):
    path = HERE / name
    if not path.exists():
        raise AssertionError("feature unavailable: " + name)
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mutation(data, offset, content):
    result = bytearray(data)
    result[offset:offset + len(content)] = content
    return bytes(result)


def reject(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("invalid bytes were accepted")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if not out.is_relative_to(HERE / "build"):
        parser.error("Evidence must be inside own build")
    out.mkdir(parents=True, exist_ok=False)
    raw = BOOT.read_bytes()
    assert len(raw) == 41943040
    assert digest(raw) == "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28"
    resource = raw[33873920:38365696]
    dtbs = raw[38367232:40018101]
    cases = []

    def run(name, call):
        try:
            call()
            cases.append({"name": name, "passed": True})
        except Exception as error:
            cases.append({"name": name, "passed": False,
                          "error": type(error).__name__ + ": " + str(error)})

    def header():
        parsed = load("audit-boot.py").inspect_boot(raw)
        assert parsed["header"]["version"] == 2
        assert parsed["header"]["page_size"] == 2048
        assert parsed["header"]["header_size"] == 1660
        assert parsed["header"]["kernel_addr"] == 268468224
        assert parsed["header"]["ramdisk_addr"] == 285212672
        assert parsed["header"]["second_addr"] == 284164096
        assert parsed["header"]["dtb_addr"] == 300941312
        assert parsed["header"]["id_sha1"] == "82ec6539338281a146f22c121f5a94bb40dff2b1"
        assert parsed["raw_bytes"] == 40019968
        expected = [
            ("kernel", 2048, 33046536, "54e75d6dbb03ab96ea938eb940fe64cab91f3f81a3e43a9e98d763980dd7779d"),
            ("ramdisk", 33050624, 822304, "072d5ce31dff79f7d4382a8e47e97732ff714043325ade4ab61c0ec67fbb0390"),
            ("second", 33873920, 4491776, "26e8a36904f2a05a9ddc3e249974cb23a33434dc04d8e2c58bb3b8c73eb0eb4d"),
            ("dtb", 38367232, 1650869, "6df7ffcee1d3cea38e08dede582377dd65a099587181a2c24ac742d03c35305a")
        ]
        assert [(x["name"], x["offset"], x["bytes"], x["sha256"])
                for x in parsed["components"]] == expected
        assert parsed["resource"]["dtb_count"] == 9 and parsed["resource"]["logo_count"] == 2
        assert len(parsed["concatenated_dtbs"]) == 11

    def resource_good():
        parsed = load("audit-boot.py").inspect_resource(resource)
        assert len(parsed["entries"]) == 11
        assert parsed["entries"][6]["path"] == "arch/arm64/boot/dts/rockchip/rk3568_smdt_3568a_v20.dtb"
        assert parsed["entries"][6]["bytes"] == 148217
        assert parsed["entries"][6]["offset"] == 0x6ee * 512
        assert parsed["entries"][0]["sha1"] == "cf69acb5493c6c71698f6717129b814a3ec19f3e"
        assert all(record["hash_verified"] for record in parsed["entries"])

    def concat_good():
        parsed = load("audit-boot.py").inspect_concat_dtbs(dtbs)
        assert len(parsed) == 11
        assert parsed[0]["offset"] == 0 and parsed[-1]["offset"] + parsed[-1]["bytes"] == 1650869
        assert all(record["root_compatible"] for record in parsed)

    run("original-header-components-id-and-two-independent-dtb-fields", header)
    run("original-rsce-nine-dtb-two-logo-and-sha1", resource_good)
    run("original-concat-eleven-complete-valid-fdts", concat_good)
    for name, changed in [
        ("truncated-header", raw[:1659]),
        ("bad-magic", mutation(raw, 0, b"BADBOOT!")),
        ("wrong-version", mutation(raw, 40, struct.pack("<I", 3))),
        ("invalid-page", mutation(raw, 36, struct.pack("<I", 2047))),
        ("wrong-header-size", mutation(raw, 1644, struct.pack("<I", 1648))),
        ("component-past-eof", mutation(raw, 8, struct.pack("<I", 0xffffffff))),
        ("truncated-component", raw[:40018000]),
        ("kernel-hash-id-mismatch", mutation(raw, 2100, bytes([raw[2100] ^ 1]))),
        ("wrong-id", mutation(raw, 576, b"\x00" * 20)),
        ("nonzero-id-padding", mutation(raw, 607, b"\x01")),
        ("nonzero-header-padding", mutation(raw, 1900, b"\x01")),
        ("nonzero-component-padding", mutation(raw, 33050623, b"\x01")),
        ("nonzero-partition-tail", mutation(raw, 41943039, b"\x01")),
        ("recovery-offset-without-size", mutation(raw, 1636, struct.pack("<Q", 33873920))),
        ("cmdline-nonzero-after-terminator", mutation(raw, 500, b"A"))
    ]:
        run(name, lambda changed=changed: reject(lambda: load("audit-boot.py").inspect_boot(changed)))
    for name, changed in [
        ("rsce-truncated", resource[:511]),
        ("rsce-invalid-magic", mutation(resource, 0, b"BAD!")),
        ("rsce-table-overflow", mutation(resource, 12, struct.pack("<I", 0xffffffff))),
        ("rsce-invalid-entry-tag", mutation(resource, 512, b"BAD!")),
        ("rsce-entry-outside", mutation(resource, 512 + 260, struct.pack("<I", 0xffffffff))),
        ("rsce-entry-overlap", mutation(resource, 1024 + 260, struct.pack("<I", 12))),
        ("rsce-duplicate-path", mutation(resource, 1024 + 4, resource[512 + 4:512 + 224])),
        ("rsce-traversal-path", mutation(resource, 512 + 4, b"../escape\x00")),
        ("rsce-unterminated-path", mutation(resource, 512 + 4, b"A" * 220)),
        ("rsce-unsupported-hash", mutation(resource, 512 + 256, struct.pack("<I", 32))),
        ("rsce-sha1-mismatch", mutation(resource, 512 + 224, b"\x00" * 20)),
        ("rsce-corrupt-dtb", mutation(resource, 12 * 512 + 100, bytes([resource[12 * 512 + 100] ^ 1]))),
        ("rsce-nonzero-padding", mutation(resource, 510, b"\x01"))
    ]:
        run(name, lambda changed=changed: reject(lambda: load("audit-boot.py").inspect_resource(changed)))
    for name, changed in [
        ("concat-truncated", dtbs[:-1]),
        ("concat-bad-magic", mutation(dtbs, 0, b"BAD!")),
        ("concat-invalid-total", mutation(dtbs, 4, struct.pack(">I", 0xffffffff))),
        ("concat-struct-outside", mutation(dtbs, 8, struct.pack(">I", 0xffffffff))),
        ("concat-strings-outside", mutation(dtbs, 12, struct.pack(">I", 0xffffffff))),
        ("concat-unsupported-version", mutation(dtbs, 20, struct.pack(">I", 99))),
        ("concat-invalid-structure-token", mutation(dtbs, struct.unpack_from(">I", dtbs, 8)[0], struct.pack(">I", 99))),
        ("concat-unconsumed-tail", dtbs + b"\x00")
    ]:
        run(name, lambda changed=changed: reject(lambda: load("audit-boot.py").inspect_concat_dtbs(changed)))

    if not args.audit_only:
        def roundtrip():
            command = [sys.executable, "-B", str(HERE / "build-roundtrip.py"), "--out", str(out / "roundtrip")]
            result = subprocess.run(command, capture_output=True, text=True)
            (out / "roundtrip.stdout").write_text(result.stdout)
            (out / "roundtrip.stderr").write_text(result.stderr)
            assert result.returncode == 0, result.stderr
            image = (out / "roundtrip/boot-padded.img").read_bytes()
            assert image == raw
            assert (out / "roundtrip/boot-raw.img").stat().st_size == 40019968
            report = json.loads((out / "roundtrip/manifest.json").read_text())
            assert report["roundtrip_byte_identical"] and not report["board_tested"]
            assert report["official_mkbootimg_sha256"] == "5579fb6bcb9e89e790a70fb9ccf3c00cf56e3e46aef74d84fcb0964887e5576e"
            second = subprocess.run(command, capture_output=True, text=True)
            assert second.returncode != 0
            assert (out / "roundtrip/boot-padded.img").read_bytes() == raw
        run("official-functions-rebuild-original-and-refuse-overwrite", roundtrip)

        def source_tamper():
            source = out / "tampered-mkbootimg.py"
            source.write_bytes((HERE / "sources/mkbootimg.py").read_bytes() + b"\nraise RuntimeError('must never execute')\n")
            reject(lambda: load("build-roundtrip.py").official_module(source))
        run("official-source-sha-check-before-execution", source_tamper)

        def input_tamper():
            sample = out / "tampered-input"
            sample.write_bytes(b"wrong")
            module = load("build-roundtrip.py")
            reject(lambda: module.read_locked(sample, 41943040,
                                               "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28"))
            link = out / "symlink-input"
            link.symlink_to(BOOT)
            reject(lambda: module.read_locked(link, 41943040,
                                               "0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28"))
        run("locked-input-rejects-corruption-and-symlink", input_tamper)

    report = {"audit_only": args.audit_only, "total": len(cases),
              "passed": sum(record["passed"] for record in cases), "cases": cases,
              "input_sha256": digest(raw), "test_sha256": digest(Path(__file__).read_bytes()),
              "source_sha256": {name: digest((HERE / name).read_bytes())
                                for name in ("audit-boot.py", "build-roundtrip.py") if (HERE / name).exists()}}
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    for record in cases:
        if not record["passed"]:
            print(record["name"] + ": " + record["error"])
    print(str(report["passed"]) + "/" + str(report["total"]))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
