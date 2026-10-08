#!/usr/bin/env python3
"""Make a separate RAM initramfs from the audited effective v5 members."""

import argparse
from dataclasses import dataclass, replace
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zlib


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "outputs/rk3568-motor-alignment-20261004"
WIFI = ROOT / "outputs/rk3568-source-wifi-20261004"
RNG = ROOT / "outputs/rk3568-rng-network-20261004"
QEMU = ROOT / ".deps/qemu-user/root/usr/bin/qemu-aarch64-static"
OLD_SHA = "5c2f1c653fdfe92d21c5baa68a64a460dd9aff3b8947d526048314700e1d5844"
NEW_SHA = "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1"
ENTROPY_SHA = "a36720bbf7f5dfee2b81e8077c95b1f8a13ef58a991436f9e1f9d4ce39e8333d"
V5_SHA = "1fad91e3926db3ee58088be4e27271e6ed56d3763bd49dd152f52e09c3873c7d"
BASE_SHA = "61f44b9a46f0b15b2947fedf5de67f95914520a6f20c15701057f85957343f49"
OVERLAY_SHA = "66c736904a2517597e67df4a28fd47e7807588a5c9418c3b1e663d87e8242df5"
HELPER_SHA = "b713e277bfcd25384975acb31253254b93bdad4a70e529b403368f6dbb4dc6f6"
MODULE_SHA = "cbf55f844b59a57fb4ff67c1754df09dcee716a6385dbb463cce1ae846e4d956"
MAX_BYTES = 32 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def safe_components(path):
    require(path.is_absolute(), "expected an absolute workspace path")
    require(path == ROOT or ROOT in path.parents, "path escapes workspace")
    current = ROOT
    for component in path.relative_to(ROOT).parts:
        require(component not in ["", ".", ".."], "unsafe path component")
        current = current / component
        require(not current.is_symlink(), "refusing symlink path: " + relative(current))


def checked_file(path, expected=None):
    safe_components(path)
    require(path.is_file(), "missing input: " + relative(path))
    data = path.read_bytes()
    if expected is not None:
        require(sha(data) == expected, "input SHA mismatch: " + relative(path))
    return data


def write_new(path, data):
    safe_components(path)
    with path.open("xb") as stream:
        stream.write(data)


def write_json(path, value):
    write_new(path, (json.dumps(value, indent=2) + "\n").encode())


def run(argv, output_path, input_data=None, cwd=None):
    result = subprocess.run(
        [str(argument) for argument in argv], input=input_data,
        capture_output=True, cwd=cwd, timeout=30,
    )
    write_new(output_path, result.stdout + result.stderr)
    require(result.returncode == 0, "host command failed; see " + relative(output_path))
    return result.stdout


@dataclass(frozen=True)
class Member:
    name: str
    mode: int
    uid: int
    gid: int
    nlink: int
    mtime: int
    data: bytes
    dev_major: int = 0
    dev_minor: int = 0

    def record(self):
        kind = {stat.S_IFREG: "file", stat.S_IFDIR: "directory",
                stat.S_IFLNK: "symlink"}[stat.S_IFMT(self.mode)]
        return {"path": self.name, "type": kind, "mode": oct(self.mode),
                "uid": self.uid, "gid": self.gid, "nlink": self.nlink,
                "archive_dev_major": self.dev_major,
                "archive_dev_minor": self.dev_minor,
                "mtime": self.mtime, "bytes": len(self.data),
                "sha256": sha(self.data),
                "link": self.data.decode() if kind == "symlink" else None}


def safe_name(name):
    require(name != "" and not name.startswith("/"), "absolute or empty member path")
    require("\x00" not in name and "\\" not in name, "unsafe member name")
    parts = name.split("/")
    require(all(part not in ["", ".", ".."] for part in parts), "member path traversal")
    require(str(PurePosixPath(name)) == name, "noncanonical member path")


def validate_member(member):
    safe_name(member.name)
    require(member.uid == 0 and member.gid == 0, "member is not root-owned")
    kind = stat.S_IFMT(member.mode)
    require(kind in [stat.S_IFDIR, stat.S_IFREG, stat.S_IFLNK], "special inode refused")
    require((member.mode & 0o7000) == 0, "special permission bits refused")
    if kind == stat.S_IFDIR:
        require(not member.data and member.nlink >= 2, "invalid directory")
        require(stat.S_IMODE(member.mode) == 0o755, "unexpected directory mode")
    elif kind == stat.S_IFLNK:
        require(member.name.startswith("bin/") and member.data == b"busybox",
                "unexpected or escaping symlink")
        require(member.nlink == 1 and stat.S_IMODE(member.mode) == 0o777,
                "invalid symlink metadata")
    else:
        require(member.nlink == 1, "regular hardlinks refused")
        require(stat.S_IMODE(member.mode) in [0o644, 0o755], "unexpected file mode")


def parse_newc(data):
    require(len(data) <= MAX_BYTES, "uncompressed archive exceeds limit")
    offset = 0
    result = {}
    while True:
        require(offset + 110 <= len(data), "truncated newc header")
        header = data[offset:offset + 110]
        require(header[:6] == b"070701", "expected non-CRC newc header")
        require(re.fullmatch(b"[0-9a-fA-F]{104}", header[6:]) is not None,
                "invalid newc hex header")
        fields = [int(header[6 + index * 8:14 + index * 8], 16)
                  for index in range(13)]
        _, mode, uid, gid, links, mtime, size, major, minor, rmajor, rminor, namesize, check = fields
        require(rmajor == rminor == check == 0,
                "device or checksum field refused")
        require(1 <= namesize <= 4096, "invalid newc name size")
        name_end = offset + 110 + namesize
        require(name_end <= len(data), "truncated newc filename")
        name_bytes = data[offset + 110:name_end]
        require(name_bytes[-1:] == b"\x00" and b"\x00" not in name_bytes[:-1],
                "invalid newc name termination")
        name = name_bytes[:-1].decode("utf-8", errors="strict")
        body_start = (name_end + 3) & ~3
        body_end = body_start + size
        next_offset = (body_end + 3) & ~3
        require(next_offset <= len(data), "truncated newc body")
        require(not any(data[name_end:body_start]) and not any(data[body_end:next_offset]),
                "nonzero newc alignment padding")
        body = data[body_start:body_end]
        offset = next_offset
        if name == "TRAILER!!!":
            require(size == 0 and not any(data[offset:]), "invalid trailer or trailing payload")
            break
        # c_devmajor/minor identify the archive's source filesystem, not a device inode.
        member = Member(name, mode, uid, gid, links, mtime, body, major, minor)
        validate_member(member)
        require(name not in result, "duplicate member within one newc stream")
        result[name] = member
    return result


def parse_gzip_streams(blob):
    require(0 < len(blob) <= MAX_BYTES, "compressed archive size refused")
    streams = []
    remaining = blob
    while remaining:
        require(len(streams) < 2, "unexpected additional gzip stream")
        decoder = zlib.decompressobj(31)
        raw = decoder.decompress(remaining, MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES and decoder.eof, "truncated or oversized gzip stream")
        raw += decoder.flush()
        require(len(raw) <= MAX_BYTES, "gzip expansion limit exceeded")
        consumed = len(remaining) - len(decoder.unused_data)
        require(consumed > 0, "gzip decoder made no progress")
        compressed = remaining[:consumed]
        streams.append({"compressed": compressed, "raw": raw,
                        "members": parse_newc(raw)})
        remaining = decoder.unused_data
    return streams


def effective_members(streams):
    result = {}
    for stream in streams:
        for name, member in stream["members"].items():
            if name in result:
                require(name == "bin/network-helper", "unexpected overlay replacement")
                before = result[name]
                require((before.mode, before.uid, before.gid, before.nlink)
                        == (member.mode, member.uid, member.gid, member.nlink),
                        "overlay changed helper metadata")
            result[name] = member
    for name in result:
        parent = str(PurePosixPath(name).parent)
        if parent != ".":
            require(parent in result and stat.S_ISDIR(result[parent].mode),
                    "missing directory parent or symlink traversal")
    return result


def baseline_audit(blob, expected_hashes):
    require(sha(blob) == V5_SHA, "v5 archive SHA mismatch")
    streams = parse_gzip_streams(blob)
    require(len(streams) == 2, "v5 must contain its two effective input streams")
    require(sha(streams[0]["compressed"]) == BASE_SHA, "base gzip SHA mismatch")
    require(sha(streams[1]["compressed"]) == OVERLAY_SHA, "helper overlay gzip SHA mismatch")
    require(set(streams[1]["members"]) == {"bin/network-helper"}, "unexpected helper overlay")
    members = effective_members(streams)
    require(set(members) == set(expected_hashes), "v5 effective member set changed")
    for name, member in members.items():
        require(sha(member.data) == expected_hashes[name], "effective member SHA mismatch: " + name)
    require(sha(members["bin/busybox"].data) == OLD_SHA, "wrong baseline BusyBox")
    require(sha(members["bin/network-helper"].data) == HELPER_SHA, "final helper overlay missing")
    require(sha(members["lib/modules/bcmdhd.ko"].data) == MODULE_SHA, "wrong same-kernel module")
    return streams, members


def pack_newc(members):
    chunks = []
    for inode, name in enumerate(sorted(members) + ["TRAILER!!!"], 1):
        member = members.get(name, Member(name, 0, 0, 0, 1, 0, b""))
        if name != "TRAILER!!!":
            validate_member(member)
        encoded_name = name.encode() + b"\x00"
        fields = [inode, member.mode, member.uid, member.gid, member.nlink,
                  member.mtime, len(member.data), member.dev_major, member.dev_minor,
                  0, 0, len(encoded_name), 0]
        header = b"070701" + b"".join(f"{value:08x}".encode() for value in fields)
        item = header + encoded_name
        item += b"\x00" * (-len(item) % 4)
        item += member.data
        item += b"\x00" * (-len(item) % 4)
        chunks.append(item)
    raw = b"".join(chunks)
    return raw + b"\x00" * (-len(raw) % 512)


def same_members(expected, actual):
    require(set(expected) == set(actual), "candidate member set differs")
    for name in expected:
        require(expected[name] == actual[name], "candidate metadata/content differs: " + name)


def load_test_module():
    path = OUTPUT / "test-serial-inspect.py"
    spec = importlib.util.spec_from_file_location("serial_inspect_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parser_tests(directory, blob, streams, baseline, expected_hashes):
    cases = []

    def rejects(label, action):
        try:
            action()
        except (ValueError, UnicodeError, zlib.error) as error:
            cases.append({"case": label, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("fault accepted: " + label)

    # A first-stream-only reader silently selects the older helper; audit must reject it.
    naive = effective_members(streams[:1])
    require(sha(naive["bin/network-helper"].data) != HELPER_SHA, "missing red overlay difference")
    write_json(directory / "overlay-red.json", {
        "status": "EXPECTED_RED_FIRST_STREAM_LOSES_FINAL_HELPER",
        "actual_helper_sha256": sha(naive["bin/network-helper"].data),
        "required_helper_sha256": HELPER_SHA, "board_tested": False,
    })
    rejects("first-stream-only", lambda: baseline_audit(streams[0]["compressed"], expected_hashes))
    rejects("truncated-gzip", lambda: parse_gzip_streams(blob[:-8]))
    damaged = bytearray(blob)
    damaged[-8] ^= 1
    rejects("gzip-CRC-damage", lambda: parse_gzip_streams(bytes(damaged)))
    rejects("third-gzip-stream", lambda: parse_gzip_streams(blob + streams[1]["compressed"]))
    raw = streams[0]["raw"]
    rejects("truncated-newc", lambda: parse_newc(raw[:500]))
    rejects("newc-trailing-payload", lambda: parse_newc(raw + b"unexpected"))
    helper = baseline["bin/network-helper"]
    rejects("member-traversal", lambda: validate_member(replace(helper, name="../escape")))
    rejects("absolute-member", lambda: validate_member(replace(helper, name="/bin/helper")))
    rejects("non-root-owner", lambda: validate_member(replace(helper, uid=1000)))
    rejects("special-inode", lambda: validate_member(replace(helper, mode=stat.S_IFCHR | 0o644)))
    rejects("hardlink", lambda: validate_member(replace(helper, nlink=2)))
    rejects("symlink-escape", lambda: validate_member(replace(
        baseline["bin/sh"], data=b"../../outside")))
    wrong = dict(baseline)
    wrong["lib/modules/bcmdhd.ko"] = replace(wrong["lib/modules/bcmdhd.ko"], data=b"wrong module")
    rejects("wrong-module-payload", lambda: same_members(baseline, parse_newc(pack_newc(wrong))))
    credentials = dict(baseline)
    credentials["etc/wpa.conf"] = Member("etc/wpa.conf", stat.S_IFREG | 0o644, 0, 0, 1, 0,
                                         b"network={\n}\n")
    rejects("unexpected-credentials-path", lambda: same_members(
        baseline, parse_newc(pack_newc(credentials))))
    write_json(directory / "archive-failure-tests.json", {
        "status": "ARCHIVE_FAILURE_BOUNDARIES_PASSED", "cases_passed": len(cases),
        "cases": cases, "board_tested": False,
    })


def elf_audit(path, directory):
    header = run(["aarch64-linux-gnu-readelf", "-h", path],
                 directory / (path.name + ".elf-header.txt")).decode()
    layout = run(["aarch64-linux-gnu-readelf", "-l", "-d", path],
                 directory / (path.name + ".elf-layout.txt")).decode()
    require("AArch64" in header and "ELF64" in header, "wrong ELF architecture")
    require("INTERP" not in layout and "NEEDED" not in layout, "dynamic ELF dependency refused")


def independent_extract(directory, raw, members):
    cpio = shutil.which("cpio")
    require(cpio is not None, "host cpio unavailable")
    listing = run([cpio, "-itv", "--numeric-uid-gid", "--quiet"],
                  directory / "cpio-independent-list.txt", raw).decode()
    require(len(listing.splitlines()) == len(members), "independent cpio count differs")
    for line in listing.splitlines():
        parts = line.split(maxsplit=8)
        require(len(parts) == 9 and parts[2:4] == ["0", "0"],
                "independent cpio owner differs")
        path = parts[8].split(" -> ", 1)[0]
        require(path in members, "independent cpio path differs")
        member = members[path]
        require(parts[0] == stat.filemode(member.mode)
                and int(parts[1]) == member.nlink and int(parts[4]) == len(member.data),
                "independent cpio metadata differs: " + path)
    extraction = directory / "extracted"
    extraction.mkdir()
    # All names, links, parent types and regular hardlink counts were audited first.
    run([cpio, "-i", "--make-directories", "--no-preserve-owner", "--quiet"],
        directory / "cpio-independent-extract.txt", raw, extraction)
    paths = {path.relative_to(extraction).as_posix(): path for path in extraction.rglob("*")}
    require(set(paths) == set(members), "independent extraction member set differs")
    for name, member in members.items():
        path = paths[name]
        metadata = path.lstat()
        require(metadata.st_mode == member.mode, "extracted mode differs: " + name)
        if stat.S_ISREG(member.mode):
            require(sha(path.read_bytes()) == sha(member.data), "extracted file differs: " + name)
        elif stat.S_ISLNK(member.mode):
            require(os.readlink(path).encode() == member.data, "extracted link differs: " + name)
    return extraction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="v1")
    arguments = parser.parse_args()
    require(re.fullmatch(r"v[1-9][0-9]*", arguments.revision) is not None, "invalid revision")
    safe_components(OUTPUT)
    output = OUTPUT / "build/userspace" / arguments.revision
    safe_components(output)
    manifest_path = OUTPUT / "userspace-manifest.json"
    require(not os.path.lexists(output) and not os.path.lexists(manifest_path),
            "refusing existing output or manifest")

    inputs = {}

    def read(path, expected=None):
        data = checked_file(path, expected)
        inputs[relative(path)] = sha(data)
        return data

    blob = read(WIFI / "initramfs-v5.cpio.gz", V5_SHA)
    result_data = read(WIFI / "result.json",
                       "394a35378c3cd3c3fbce84b2b7cdc4c3470512809970a24c559f8c6d63fae9b3")
    hashes = json.loads(result_data)["effective_archive_sha256"]
    # The historical record lists nonempty files and links; bind its empty entries explicitly.
    for name in ["bin", "dev", "dev/pts", "etc", "lib", "lib/firmware", "lib/modules",
                 "mnt", "mnt/cache", "proc", "sys", "tmp", "etc/resolv.conf"]:
        require(name not in hashes, "historical empty-entry expectation changed")
        hashes[name] = sha(b"")
    streams, baseline = baseline_audit(blob, hashes)
    read(WIFI / "initramfs.cpio.gz", BASE_SHA)
    read(WIFI / "helper-overlay-final.cpio.gz", OVERLAY_SHA)
    for name in ["network-helper", "wpa_supplicant", "wpa_cli"]:
        require(read(WIFI / name, hashes["bin/" + name]) == baseline["bin/" + name].data,
                "effective network payload differs from original artifact")
    read(WIFI / "bcmdhd.ko", MODULE_SHA)
    read(WIFI / "network-helper.c", "8a8bfa224f8b0aa07537214e365afc7ecdf3deced5497aae5a5a085e76ed70ce")
    read(WIFI / "dhcp-script.sh", hashes["etc/udhcpc.sh"])
    read(ROOT / "outputs/rk3568-source-userspace-20261004/ram-init.sh", hashes["init"])

    busybox_path = RNG / "build/busybox-module-options/v1/busybox"
    busybox_data = read(busybox_path, NEW_SHA)
    bb_manifest = json.loads(read(RNG / "busybox-module-options-manifest.json",
                                  "1f85b3e719d9a33595b0a173855995aef33787549367cc22862720b0c4620446"))
    require(bb_manifest["artifact"]["sha256"] == NEW_SHA
            and bb_manifest["config_changes"] == {
                "CONFIG_FEATURE_CMDLINE_MODULE_OPTIONS": {"before": "n", "after": "y"}}
            and bb_manifest["module_argument_mock_cases_passed"] == 4
            and not bb_manifest["real_kernel_module_syscalls_forwarded"],
            "BusyBox module-option evidence mismatch")
    for name, expected in [
        ("red-result.json", "bb8df13a55b427e2e37eef9ec29a200c6ab5956610fd872bdae57d1b311f1c63"),
        ("green-result.json", "937d7c079360c05d0499df66f4b46c6af1c42118b790e3c09754e2e864cf5bb9"),
    ]:
        read(RNG / "build/busybox-module-options/v1" / name, expected)
    read(RNG / "build-busybox-module-options.py", bb_manifest["source_script_sha256"])
    config_path = RNG / "build/busybox-module-options/v1/busybox-1.36.1/.config"
    read(config_path, bb_manifest["new_config_sha256"])
    read(ROOT / bb_manifest["complete_config_diff"], bb_manifest["complete_config_diff_sha256"])

    entropy_data = read(RNG / "entropy-check", ENTROPY_SHA)
    entropy_manifest = json.loads(read(RNG / "entropy-manifest.json",
                                       "0e1aec7dd105a0b6e106a58bfcd848be5ca134d63c44ed7f5b10a33b025afcbc"))
    require(entropy_manifest["artifact"]["sha256"] == ENTROPY_SHA, "entropy manifest mismatch")
    for name, expected in entropy_manifest["source_files"].items():
        read(ROOT / name, expected)
    read(OUTPUT / "serial-inspect.c")
    read(OUTPUT / "test-serial-inspect.py")
    read(Path(__file__).resolve())
    licenses = [WIFI / "wpa-LICENSE", WIFI / "libnl-LICENSE",
                RNG / "build/busybox-module-options/v1/busybox-1.36.1/LICENSE"]
    for path in licenses:
        read(path)
    read(ROOT / "outputs/rk3568-rcu-reset-20261004/Image",
         "e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457")
    checked_file(QEMU)
    output.mkdir(parents=True)

    parser_tests(output, blob, streams, baseline, hashes)
    inspector = output / "serial-inspect"
    compiler = Path(shutil.which("aarch64-linux-gnu-gcc") or "missing").resolve()
    compile_argv = [str(compiler), "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                    "-static", str(OUTPUT / "serial-inspect.c"), "-o", str(inspector)]
    run(compile_argv, output / "serial-build.txt")
    compiler_version = run([compiler, "--version"], output / "compiler-version.txt").decode()

    tests = load_test_module()
    # Intentionally wrong source sends one byte to this host-only PTY. The real test must fail.
    wrong_source = output / "serial-wrong-sends-byte.c"
    write_new(wrong_source, b"#include <fcntl.h>\n#include <stdio.h>\n#include <unistd.h>\n"
              b"int main(int argc, char **argv) {\n"
              b"    if (argc != 3) return 2;\n"
              b"    int fd = open(argv[2], O_WRONLY | O_NOCTTY | O_NONBLOCK);\n"
              b"    if (fd < 0) return 2;\n"
              b"    if (write(fd, \"X\", 1) != 1) return 2;\n"
              b"    close(fd);\n    puts(\"{}\");\n    return 0;\n}\n")
    wrong_binary = output / "serial-wrong-sends-byte"
    run([compiler, "-static", "-Wall", "-Wextra", "-Werror", wrong_source, "-o", wrong_binary],
        output / "serial-red-build.txt")
    try:
        tests.pty_case(QEMU, wrong_binary, tests.termios.B115200, False, 1, False)
    except ValueError as error:
        require(str(error) == "inspector sent bytes to the PTY", "wrong red failure")
        write_json(output / "serial-red.json", {
            "status": "EXPECTED_RED_TTY_WRITE_DETECTED", "reason": str(error),
            "fixture_is_host_pty": True, "board_tested": False,
        })
    else:
        raise ValueError("serial test failed to detect UART write baseline")
    serial_record = tests.run_suite(QEMU, inspector, output / "serial-tests")

    members = dict(baseline)
    members["bin/busybox"] = replace(baseline["bin/busybox"], data=busybox_data)
    members["bin/entropy-check"] = Member("bin/entropy-check", stat.S_IFREG | 0o755,
                                          0, 0, 1, 0, entropy_data)
    members["bin/serial-inspect"] = Member("bin/serial-inspect", stat.S_IFREG | 0o755,
                                           0, 0, 1, 0, inspector.read_bytes())
    raw = pack_newc(members)
    packed = gzip.compress(raw, compresslevel=9, mtime=0)
    candidate = output / "initramfs.cpio.gz"
    write_new(candidate, packed)
    verified = parse_gzip_streams(candidate.read_bytes())
    require(len(verified) == 1, "candidate must contain one gzip/newc stream")
    same_members(members, effective_members(verified))
    extraction = independent_extract(output, raw, members)
    for name in ["busybox", "wpa_supplicant", "wpa_cli", "network-helper",
                 "entropy-check", "serial-inspect"]:
        elf_audit(extraction / "bin" / name, output)
    applets = run([QEMU, extraction / "bin/busybox", "--list"], output / "applets.txt").decode().splitlines()
    old_links = sorted(name[len("bin/"):] for name, member in baseline.items()
                       if name.startswith("bin/") and stat.S_ISLNK(member.mode))
    require(sorted(applets) == old_links and len(applets) == 52, "BusyBox applets changed")
    require("stty" not in applets, "unexpected stty configuration expansion")
    shell = run([QEMU, extraction / "bin/busybox", "sh", "-c", "printf 'USERSPACE_SHELL_OK\\n'"],
                output / "qemu-shell.txt")
    require(shell == b"USERSPACE_SHELL_OK\n", "candidate shell check failed")
    entropy = run([QEMU, extraction / "bin/entropy-check", "--check"], output / "qemu-entropy.txt")
    require(entropy == b"CRNG_READY\n", "host QEMU entropy check failed")
    tests.run_suite(QEMU, extraction / "bin/serial-inspect", output / "serial-extracted-tests")
    run([QEMU, extraction / "bin/wpa_supplicant", "-v"], output / "qemu-wpa-version.txt")
    run([QEMU, extraction / "bin/wpa_cli", "-v"], output / "qemu-wpa-cli-version.txt")

    changed = sorted(name for name in members if name not in baseline or members[name] != baseline[name])
    require(changed == ["bin/busybox", "bin/entropy-check", "bin/serial-inspect"],
            "unrequested effective payload change")
    write_json(output / "baseline-effective-members.json", [baseline[name].record() for name in sorted(baseline)])
    write_json(output / "candidate-effective-members.json", [members[name].record() for name in sorted(members)])
    # Recheck every input after building; old archives and tools are read-only dependencies.
    for name, expected in inputs.items():
        checked_file(ROOT / name, expected)
    manifest = {
        "schema": 1, "status": "RAM_USERSPACE_CANDIDATE_HOST_VERIFIED",
        "inputs_sha256": inputs,
        "baseline_streams": [{"index": index, "compressed_bytes": len(stream["compressed"]),
                              "compressed_sha256": sha(stream["compressed"]),
                              "newc_bytes": len(stream["raw"]), "members": len(stream["members"])}
                             for index, stream in enumerate(streams)],
        "baseline_effective_members": len(baseline),
        "candidate_effective_members": len(members), "effective_changes": changed,
        "effective_member_records": relative(output / "candidate-effective-members.json"),
        "effective_member_records_sha256": sha((output / "candidate-effective-members.json").read_bytes()),
        "artifact": {"path": relative(candidate), "bytes": len(packed), "sha256": sha(packed),
                     "crc32": f"{zlib.crc32(packed):08x}", "newc_bytes": len(raw), "gzip_streams": 1},
        "serial_inspect": {"path": "/bin/serial-inspect", "bytes": inspector.stat().st_size,
                           "sha256": sha(inspector.read_bytes()), "compile_argv": compile_argv,
                           "compiler_sha256": sha(compiler.read_bytes()), "compiler_version": compiler_version,
                           "test_record": relative(output / "serial-tests/result.json"),
                           "test_record_sha256": sha((output / "serial-tests/result.json").read_bytes()),
                           "host_pty_cases_passed": serial_record["cases_passed"],
                           "application_termios_setter_or_tty_data_io": False,
                           "open_may_have_hardware_side_effects": True,
                           "driver_echo_may_transmit_on_physical_tty": True,
                           "not_board_used": True},
        "busybox_module_argument_evidence": bb_manifest["module_argument_evidence"],
        "busybox_module_argument_mock_cases_passed": 4,
        "busybox_applet_count": len(applets), "stty_included": False,
        "codec_pty_tests_included": False,
        "firmware": {name: {"sha256": hashes[name], "classification": "binary-private-local-only",
                            "redistribution_license_verified": False}
                     for name in hashes if name.startswith("lib/firmware/")},
        "licenses_sha256": {relative(path): inputs[relative(path)] for path in licenses},
        "init_unchanged": True, "credentials_packaged": False,
        "network_autostart_added": False, "android_manufacturer_so_packaged": False,
        "independent_cpio_all_metadata_and_payload_verified": True,
        "host_qemu_static_elf_verified": True, "old_inputs_unchanged": True,
        "board_tested": False, "physical_uart_tested": False,
        "board_module_parameter_behavior_tested": False,
    }
    write_json(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "artifact": manifest["artifact"],
                      "members": len(members), "serial_host_cases": serial_record["cases_passed"],
                      "board_tested": False}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, zlib.error) as error:
        print("USERSPACE_BUILD_FAILED:", error, file=sys.stderr)
        sys.exit(2)
