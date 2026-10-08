#!/usr/bin/env python3
"""Verify current source/artifact binding and save actual runtime checks."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="v1")
    args = parser.parse_args()
    if not args.revision.startswith("v") or not args.revision[1:].isdigit():
        parser.error("revision must be vN")
    output = HERE / "build" / ("host-checks-" + args.revision)
    if output.exists() or output.is_symlink():
        raise ValueError("Refuse existing verification output")
    output.mkdir()
    commands = ["test-return-guard.py", "check-runtime-commands.py"]
    actual = {}
    for script in commands:
        run = subprocess.run([sys.executable, str(HERE / script)], check=True, capture_output=True, text=True)
        (output / (script + ".stdout.json")).write_text(run.stdout)
        (output / (script + ".stderr.txt")).write_text(run.stderr)
        actual[script] = json.loads(run.stdout)
    dt = json.loads((HERE / "build/dtb-v3/manifest.json").read_text())
    board = ROOT / "platforms/rk3568/boards/aiot-3568pq/bsp"
    for field, path in {
        "source_sha256": board / "rk3568-aiot-3568pq-cap1188-spi.dts",
        "builder_sha256": HERE / "build-dtb.py",
        "audit_script_sha256": board.parent / "verify-cap1188-spi.py",
        "fault_test_script_sha256": board.parent / "test-cap1188-spi-audit.py",
        "dtb_sha256": HERE / "build/dtb-v3/cap1188-spi.dtb",
        "image_sha256": ROOT / "outputs/rk3568-rcu-reset-20261004/Image",
    }.items():
        if digest(path) != dt[field]:
            raise ValueError("DT/artifact input changed: " + field)
    helper = json.loads((HERE / "build/inspect-v1/manifest.json").read_text())
    for field, path in {
        "source_sha256": HERE / "cap1188-inspect.c", "test_script_sha256": HERE / "test-cap1188-inspect.py",
        "builder_sha256": HERE / "build-inspect.py", "binary_sha256": HERE / "build/inspect-v1/cap1188-inspect",
    }.items():
        if digest(path) != helper[field]:
            raise ValueError("Helper source changed: " + field)
    for label, item in helper["tests"].items():
        test_result = HERE / "build" / ("inspect-tests-" + label) / "result.json"
        if digest(test_result) != item["result_sha256"]:
            raise ValueError("Helper test result changed")
    initial = json.loads((HERE / "runtime-manifest.json").read_text())
    runtime_file = HERE / "runtime-manifest-v2.json"
    runtime = json.loads((runtime_file if runtime_file.exists() else HERE / "runtime-manifest.json").read_text())
    if digest(HERE / "linux-stage.sh") != runtime["stage_script_sha256"]:
        raise ValueError("Bootstrap script changed")
    for name, sha in runtime["files"].items():
        current = HERE / name if name.endswith(".sh") else HERE / "build/staging-v1" / name
        if digest(current) != sha or digest(HERE / "build/staging-v1" / name) != initial["files"][name]:
            raise ValueError("Staging input changed: " + name)
    stage = json.loads((HERE / "build/stage-tests-v1.json").read_text())
    if stage["source_sha256"] != digest(HERE / "linux-stage.sh"):
        raise ValueError("Stage fixtures bound to different script")
    kernel = ROOT / "third_party/linux-rk3588"
    commit = subprocess.check_output(["git", "-C", str(kernel), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "-C", str(kernel), "status", "--porcelain"], text=True)
    if commit != dt["kernel_commit"] or status:
        raise ValueError("Locked kernel tree changed")
    result = {"status": "CAP_CURRENT_HOST_ARTIFACTS_VERIFIED", "actual_runtime_checks": actual,
              "stage_fixture_result": stage, "dtb_checks": dt["checks_passed"], "dtb_faults_rejected": dt["faults_rejected"],
              "helper_host_cases": helper["tests"]["green-v3"]["cases"],
              "helper_qemu_cases": helper["tests"]["green-v4"]["cases"],
              "locked_kernel_commit": commit, "locked_kernel_clean": True,
              "board_access_in_this_verifier": False}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
