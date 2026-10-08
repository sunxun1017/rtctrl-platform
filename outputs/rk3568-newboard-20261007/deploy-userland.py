#!/usr/bin/env python3
"""Deploy existing static diagnostics into one new Android temporary directory."""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
SOURCE = ROOT / "outputs/rk3568-pid1-20261005/build/production-v3/stage"
FILES = {
    "busybox": ("bin/busybox", "514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1"),
    "codec-test": ("usr/bin/codec-test", "18fd4744d881e46661d16ad60112f395262b6a6e97ce83f246a4334f6448234c"),
    "pty-test": ("usr/bin/pty-test", "5eb5fd9aba8133933dce602d5e0dbd3acf5f1829f700615dc77a67b5f1d0cbda"),
}
EXPECTED_FDT = "7438f8f456bedf09353c19be96127a79ca570a8e09b47c9e92e90829705c76cc"
REMOTE = "/data/local/tmp/rtctrl-newboard-20261007"
PARTITIONS = ("boot", "recovery", "dtbo", "uboot", "trust", "vbmeta", "baseparameter", "misc")


def verified_backups(base):
    backup = json.loads((base / "backups-v1/receipt.json").read_text())
    entries = backup["entries"]
    if any(entry.get("exit_code", 0) != 0 for entry in entries):
        raise RuntimeError("Backup commands did not all succeed")
    files = [entry for entry in entries if "remote_before_local_after_match" in entry]
    required = {"/dev/block/by-name/" + name for name in PARTITIONS}
    if len(files) != len(required) or {entry["remote"] for entry in files} != required:
        raise RuntimeError("Eight unique complete partition backups are required")
    verified = {}
    for entry in files:
        expected_name = entry["remote"].rsplit("/", 1)[1] + ".img"
        if entry["name"] != expected_name or entry["remote_before_local_after_match"] is not True:
            raise RuntimeError("Unexpected backup identity: " + entry["remote"])
        data = (base / "backups-v1" / expected_name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != entry["bytes"] or digest != entry["sha256"]:
            raise RuntimeError("Local backup no longer matches: " + expected_name)
        verified[entry["remote"]] = digest
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    expected_partitions = verified_backups(BASE)
    out = BASE / "runtime-v1"
    out.mkdir(exist_ok=False)
    steps = []
    receipt = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "remote_directory": REMOTE,
        "kernel_transition": False,
        "physical_uart_opened": False,
        "actuator_commands": False,
        "steps": steps,
        "completed": False,
    }

    def run(name, arguments, timeout=30):
        argv = ["adb", "-s", args.serial, *arguments]
        result = subprocess.run(argv, capture_output=True, timeout=timeout)
        (out / (name + ".stdout")).write_bytes(result.stdout)
        (out / (name + ".stderr")).write_bytes(result.stderr)
        steps.append({"name": name, "argv": argv, "exit_code": result.returncode})
        print(name, "exit", result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError("Failed: " + name)
        return result.stdout

    def shell(name, command):
        return run(name, ["shell", command])

    try:
        if shell("root-check", "id -u").strip() != b"0":
            raise RuntimeError("Root unavailable")
        if shell("fdt-check", "sha256sum /sys/firmware/fdt").split()[0].decode() != EXPECTED_FDT:
            raise RuntimeError("Board changed since read-only baseline")
        boot_before = shell("boot-id-before", "cat /proc/sys/kernel/random/boot_id").strip()
        for name, (relative, digest) in FILES.items():
            if hashlib.sha256((SOURCE / relative).read_bytes()).hexdigest() != digest:
                raise RuntimeError("Local source artifact changed: " + name)
        shell("create-task-directory", "\n".join([
            "set -eu", "umask 077", "test ! -e " + REMOTE,
            "mkdir " + REMOTE,
        ]))
        for name, (relative, digest) in FILES.items():
            remote = REMOTE + "/" + name
            run("push-" + name, ["push", str(SOURCE / relative), remote])
            if shell("hash-" + name, "sha256sum " + remote).split()[0].decode() != digest:
                raise RuntimeError("Board artifact hash mismatch: " + name)
            shell("permissions-" + name, "chmod 700 " + remote)
        checks = (
            ("busybox", REMOTE + "/busybox uname -m", b"aarch64"),
            ("kernel", REMOTE + "/busybox uname -r", b"4.19.232"),
            ("codec", REMOTE + "/codec-test", b"PatchX codec: vectors, fragmentation, corruption, bounds and byte transport passed"),
            ("pty", REMOTE + "/pty-test", b"PatchX POSIX PTY: idle, exact TX, fragmented RX, corruption, reopen and hangup passed"),
        )
        for name, command, expected in checks:
            output = shell("run-" + name, command)
            if output.strip() != expected:
                raise RuntimeError("Unexpected diagnostic output: " + name)
            print(output.decode().strip(), flush=True)
        if shell("boot-id-after", "cat /proc/sys/kernel/random/boot_id").strip() != boot_before:
            raise RuntimeError("Unexpected board restart")
        hashes = shell("protected-partitions-after", "sha256sum " + " ".join(
            "/dev/block/by-name/" + name for name in PARTITIONS
        ))
        actual = {line.split()[1].decode(): line.split()[0].decode() for line in hashes.splitlines()}
        if len(hashes.splitlines()) != len(expected_partitions) or set(actual) != set(expected_partitions):
            raise RuntimeError("Incomplete protected partition hashes")
        for remote, digest in expected_partitions.items():
            if actual[remote] != digest:
                raise RuntimeError("Protected partition changed: " + remote)
        receipt["protected_partition_count"] = len(actual)
        receipt["protected_partitions_unchanged"] = True
        receipt["boot_id_unchanged"] = True
        receipt["completed"] = True
    finally:
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (out / "receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )


if __name__ == "__main__":
    main()
