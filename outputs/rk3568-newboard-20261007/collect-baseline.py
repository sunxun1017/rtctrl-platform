#!/usr/bin/env python3
"""Finite read-only ADB baseline for the replacement board."""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    entries = []

    def query(name, command, timeout=30):
        argv = ["adb", "-s", args.serial, "shell", command]
        result = subprocess.run(argv, capture_output=True, timeout=timeout)
        (args.out / (name + ".stdout")).write_bytes(result.stdout)
        (args.out / (name + ".stderr")).write_bytes(result.stderr)
        entry = {
            "name": name,
            "argv": argv,
            "exit_code": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
        }
        entries.append(entry)
        print(name, "exit", result.returncode, flush=True)
        return result

    def download(name, remote, maximum, expected_size=None):
        before = query(name + "-before", "sha256sum " + remote)
        if before.returncode:
            raise RuntimeError("Cannot read initial hash: " + name)
        result = subprocess.run(
            ["adb", "-s", args.serial, "exec-out", "cat", remote],
            capture_output=True,
            timeout=60,
        )
        (args.out / (name + "-download.stderr")).write_bytes(result.stderr)
        if result.returncode or len(result.stdout) > maximum:
            raise RuntimeError("Download failed or exceeded bound: " + name)
        if expected_size is not None and len(result.stdout) != expected_size:
            raise RuntimeError("Incomplete partition download: " + name)
        digest = hashlib.sha256(result.stdout).hexdigest()
        after = query(name + "-after", "sha256sum " + remote)
        matches = (
            after.returncode == 0
            and before.stdout.split()[0].decode() == digest
            and after.stdout.split()[0].decode() == digest
        )
        if not matches:
            raise RuntimeError("Remote/local hash mismatch: " + name)
        (args.out / name).write_bytes(result.stdout)
        entries.append({
            "name": name,
            "remote": remote,
            "bytes": len(result.stdout),
            "sha256": digest,
            "remote_before_local_after_match": True,
        })
        print(name, len(result.stdout), digest, flush=True)

    started = datetime.now(timezone.utc).isoformat()
    completed = False
    try:
        if args.backup:
            for partition in (
                "boot", "recovery", "dtbo", "uboot", "trust", "vbmeta",
                "baseparameter", "misc",
            ):
                remote = "/dev/block/by-name/" + partition
                size = query(partition + "-size", "blockdev --getsize64 " + remote)
                if size.returncode:
                    raise RuntimeError("Cannot read partition size: " + partition)
                if not 0 < int(size.stdout) <= 128 * 1024 * 1024:
                    raise RuntimeError("Unexpected partition size: " + partition)
                download(partition + ".img", remote, int(size.stdout), int(size.stdout))
        else:
            query("identity", "\n".join([
                "id", "uname -a", "getprop ro.build.version.release",
                "getprop ro.build.fingerprint", "getprop ro.product.board",
                "getprop sys.boot_completed", "cat /proc/device-tree/model",
                "cat /proc/device-tree/compatible", "cat /proc/cmdline",
            ]))
            query("resources", "\n".join([
                "cat /proc/meminfo", "cat /proc/uptime",
                "df -k /data /cache /sdcard", "cat /proc/partitions",
                "ls -l /dev/block/by-name", "dumpsys battery",
            ]))
            query("peripherals", "\n".join([
                "cat /proc/asound/cards", "cat /proc/asound/pcm",
                "cat /proc/tty/driver/serial",
                "ls -l /dev/ttySMT* /dev/ttyFIQ* /dev/McuCom",
                "ls -l /sys/class/backlight /sys/class/drm",
                "cat /sys/class/backlight/backlight/brightness",
                "cat /sys/class/backlight/backlight/max_brightness",
                "cat /sys/class/drm/card0-DSI-1/status",
                "cat /sys/class/drm/card0-DSI-1/modes",
                "cat /proc/bus/input/devices",
            ]))
            query("drivers", "\n".join([
                "cat /proc/modules", "ls -l /sys/bus/i2c/devices",
                "ls -l /sys/bus/spi/devices", "ls -l /sys/class/video4linux",
                "ls -l /sys/bus/usb/devices",
                "ps -A -o PID,NAME", "wm size", "wm density",
            ]))
            query("kernel-log", "dmesg")
            download("android-live.dtb", "/sys/firmware/fdt", 2 * 1024 * 1024)
        completed = True
    finally:
        receipt = {
            "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "adb_serial": args.serial,
            "scope": "read-only Android baseline and local backup",
            "board_writes": False,
            "reboot": False,
            "actuator_commands": False,
            "completed": completed,
            "entries": entries,
        }
        (args.out / "receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
