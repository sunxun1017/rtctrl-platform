#!/usr/bin/env python3
"""Recheck the final source and RAM script tests without accessing a board."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOARD = ROOT / "platforms/rk3568/boards/aiot-3568pq"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", choices=["v1", "v2", "v3"], default="v1")
    args = parser.parse_args()
    output = HERE / "private" / ("final-verification-" + args.revision)
    if output.exists() or output.is_symlink() or output.parent.is_symlink():
        raise ValueError("Refusing existing or symlink verification output")
    output.mkdir()
    # Labels refer to fresh test directories, not new deployed binaries.
    label_number = {"v1": 4, "v2": 6, "v3": 8}[args.revision]
    dtb = HERE / "build/dtb-v3/accelerometer.dtb"
    pp = HERE / "build/dtb-v3/accelerometer.pp.dts"
    commands = {
        "runtime-dependencies": [HERE / "check-runtime-commands.py"],
        "reset-guard": [HERE / "test-return-guard.py"],
        "dtb-audit": [BOARD / "verify-accelerometer.py", dtb],
        "dtb-faults": [BOARD / "test-accelerometer-audit.py", dtb, pp],
        "linux-helper": [HERE / "test-sensor-inspect.py"],
        "driver-functions": [HERE / "test-driver-functions.py", "--source-dir",
                             HERE / "driver-source-v1/drivers/input/sensors",
                             "--label", "green-v" + str(label_number)],
        "android-helper-host": [HERE / "test-android-identity.py", "--label",
                                "green-v" + str(label_number)],
        "android-helper-qemu": [HERE / "test-android-identity.py", "--label",
                                "green-v" + str(label_number + 1), "--aarch64-qemu"],
    }
    results = {}
    for name, arguments in commands.items():
        argv = [sys.executable, *map(str, arguments)]
        process = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120)
        transcript = output / (name + ".txt")
        transcript.write_text(process.stdout + process.stderr)
        results[name] = {
            "exit_code": process.returncode,
            "script": str(Path(arguments[0]).relative_to(ROOT)),
            "script_sha256": hashlib.sha256(Path(arguments[0]).read_bytes()).hexdigest(),
            "transcript_sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
        }
        print(name + ": " + ("PASS" if process.returncode == 0 else "FAIL"), flush=True)
        if process.returncode:
            print(process.stdout + process.stderr, flush=True)
            break
    record = {
        "results": results,
        "complete": len(results) == len(commands),
        "failures": sum(item["exit_code"] != 0 for item in results.values()),
        "driver_function_result": "driver-tests-green-v" + str(label_number) + "/result.json",
        "android_host_result": "build/android-identity-tests-green-v" + str(label_number) + "/result.json",
        "android_qemu_result": "build/android-identity-tests-green-v" + str(label_number + 1) + "/result.json",
        "board_access": False,
    }
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    if not record["complete"] or record["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
