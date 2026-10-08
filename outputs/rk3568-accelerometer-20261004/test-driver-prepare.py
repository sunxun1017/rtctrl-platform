#!/usr/bin/env python3
"""Run the actual preparation entry point against private patch/output fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPT = HERE / "driver-prepare.py"
PUBLISHED = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches/0005-sensor-error-propagation.patch"
KERNEL = ROOT / "third_party/linux-rk3588"
LAUNCHER = """
import importlib.util
from pathlib import Path
import sys
spec = importlib.util.spec_from_file_location("prepare_under_test", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.HERE = Path(sys.argv[2])
module.PATCH = Path(sys.argv[3])
sys.argv = [str(module.__file__), *sys.argv[4:]]
module.main()
"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(path):
    value = path.stat()
    return {"sha256": sha(path), "inode": value.st_ino, "mtime_ns": value.st_mtime_ns,
            "mode": value.st_mode, "bytes": value.st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"(?:red|green)-v[1-9][0-9]*", args.label):
        parser.error("label must be red-vN or green-vN")
    output = HERE / ("driver-prepare-tests-" + args.label)
    if output.exists() or output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Refuse existing or symlink evidence output")
    output.mkdir()
    original_patch = fingerprint(PUBLISHED)
    source_record = json.loads((HERE / "driver-source-v1/driver-source-manifest.json").read_text())
    original_source = {relative: sha(KERNEL / relative) for relative in source_record["sources"]}
    cases = []

    def invoke(name, fixture_here, patch, success, expected_error="", version="v1"):
        result = subprocess.run(["python3", "-c", LAUNCHER, str(SCRIPT), str(fixture_here), str(patch),
                                 "--version", version], capture_output=True, text=True, timeout=10)
        (output / (name + ".txt")).write_text(result.stdout + result.stderr)
        passed = result.returncode == 0 if success else result.returncode != 0 and expected_error in result.stderr
        cases.append({"name": name, "passed": passed, "exit_code": result.returncode,
                      "expected_success": success, "expected_error": expected_error,
                      "stdout": result.stdout, "stderr": result.stderr})
        return result.returncode == 0

    matching = output / "matching"
    matching.mkdir()
    matching_patch = matching / "0005.patch"
    shutil.copy2(PUBLISHED, matching_patch)
    existing_match = fingerprint(matching_patch)
    if invoke("existing-identical-patch-rebuilt", matching, matching_patch, True):
        rebuilt = matching / "driver-source-v1"
        for relative, record in source_record["sources"].items():
            if sha(rebuilt / relative) != record["candidate_sha256"]:
                cases[-1]["passed"] = False
                cases[-1]["source_mismatch"] = relative
    if fingerprint(matching_patch) != existing_match:
        raise AssertionError("Identical patch was rewritten")
    cases.append({"name": "matching-patch-inode-mtime-mode-bytes-unchanged", "passed": True})

    absent = output / "missing"
    absent.mkdir()
    absent_patch = absent / "0005.patch"
    if invoke("missing-patch-created", absent, absent_patch, True):
        if sha(absent_patch) != original_patch["sha256"]:
            cases[-1]["passed"] = False

    corrupt = output / "tampered"
    corrupt.mkdir()
    corrupt_patch = corrupt / "0005.patch"
    corrupt_patch.write_bytes(PUBLISHED.read_bytes() + b"# deliberately altered fixture\n")
    corrupt_before = fingerprint(corrupt_patch)
    invoke("tampered-patch-refused", corrupt, corrupt_patch, False, "Existing patch differs from generated patch")
    if (corrupt / "driver-source-v1").exists() or fingerprint(corrupt_patch) != corrupt_before:
        raise AssertionError("Tampered refusal must precede output writes")

    occupied = output / "occupied"
    occupied.mkdir()
    destination = occupied / "driver-source-v1"
    destination.mkdir()
    sentinel = destination / "sentinel"
    sentinel.write_bytes(b"preserve-existing-source-output\n")
    before = fingerprint(sentinel)
    invoke("existing-source-output-refused", occupied, PUBLISHED, False, "Refuse existing output")
    if fingerprint(sentinel) != before:
        raise AssertionError("Existing output modified")

    link_fixture = output / "symlink-output"
    link_fixture.mkdir()
    link_target = output / "output-target"
    link_target.mkdir()
    (link_fixture / "driver-source-v1").symlink_to(link_target, target_is_directory=True)
    invoke("symlink-source-output-refused", link_fixture, PUBLISHED, False, "Refuse existing output")

    parent_link = output / "symlink-parent"
    parent_link.symlink_to(link_target, target_is_directory=True)
    invoke("symlink-source-parent-refused", parent_link, PUBLISHED, False, "Refuse symlink output parent")

    patch_link_fixture = output / "symlink-patch"
    patch_link_fixture.mkdir()
    patch_link = patch_link_fixture / "0005.patch"
    patch_link.symlink_to(PUBLISHED)
    invoke("symlink-patch-refused", patch_link_fixture, patch_link, False, "Refuse symlink patch")

    escaping = ROOT.parent / "rtctrl-prepare-path-outside-repository"
    invoke("outside-source-output-refused", escaping, PUBLISHED, False, "Output outside repository")
    invoke("escaping-version-refused", absent, PUBLISHED, False, "version must be vN", version="../escape")

    if fingerprint(PUBLISHED) != original_patch:
        raise AssertionError("Published patch changed")
    for relative, digest in original_source.items():
        if sha(KERNEL / relative) != digest:
            raise AssertionError("Original source changed")
    status = subprocess.check_output(["git", "-C", str(KERNEL), "status", "--porcelain"], text=True)
    if status:
        raise AssertionError("Original source is dirty")
    record = {"cases": cases, "failures": sum(not case["passed"] for case in cases),
              "script_sha256": sha(SCRIPT), "test_script_sha256": sha(Path(__file__)),
              "published_patch_before_after": original_patch, "source_sha256_unchanged": original_source,
              "actual_prepare_main_executed": True,
              "fixture_overrides": ["HERE (source output directory only)", "PATCH (private ordinary-file patch fixtures only)"],
              "original_kernel_commit_check_executed": True, "source_clean": True, "board_tested": False}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    for case in cases:
        print(case["name"] + " " + ("PASS" if case["passed"] else "FAIL"))
    print("TOTAL_FAILURES=" + str(record["failures"]))
    raise SystemExit(int(record["failures"] != 0))


if __name__ == "__main__":
    main()
