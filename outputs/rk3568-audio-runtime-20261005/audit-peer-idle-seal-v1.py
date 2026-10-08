#!/usr/bin/env python3
"""Fresh root inventory readback of the accepted no-START helper archive."""
import hashlib
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SEAL = HERE / "pcm-peer-idle-v1/sealed-evidence-v1"
OUT = HERE / "build/root-peer-idle-seal-audit-v1.json"
EXPECTED = {
    "receipt.json": "c02ff1af64506a77f0920a32095d93c53991d9c6d9026e33e075eaf256569c39",
    "inventory.json": "952270f37505769e24195b826636e89ebe5c23c5b424670db5047ef91b743ac9",
    "SHA256SUMS": "7ebbea24c05ecbd6a6c15a9d4012e49295d7c71d98db491e096fbf82338837e4",
}


def read(path):
    if not path.is_relative_to(ROOT) or ".." in path.parts:
        raise ValueError("Escaped input")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Nonordinary input: " + str(path))
    for ancestor in path.parents:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError("Nonordinary ancestry")
        if ancestor == ROOT:
            break
    return path.read_bytes()


def sha(path):
    return hashlib.sha256(read(path)).hexdigest()


def main():
    if OUT.exists():
        raise ValueError("Fresh output required")
    for name, digest in EXPECTED.items():
        if sha(SEAL / name) != digest:
            raise ValueError("Changed seal " + name)
    inventory = json.loads(read(SEAL / "inventory.json"))
    receipt = json.loads(read(SEAL / "receipt.json"))
    if len(inventory["files"]) != 18771 or len(inventory["external_inputs_readback_sha256"]) != 9337:
        raise ValueError("Incomplete seal")
    actual_paths = set()
    for path in (SEAL / "source-inputs").rglob("*"):
        if stat.S_ISDIR(path.lstat().st_mode):
            continue
        read(path)
        actual_paths.add(path.relative_to(SEAL).as_posix())
    if actual_paths != set(inventory["files"]):
        raise ValueError("Archive file set differs")
    sums = {}
    for relative, entry in inventory["files"].items():
        archive = read(SEAL / relative)
        original = read(ROOT / entry["source"])
        digest = hashlib.sha256(archive).hexdigest()
        if len(archive) != entry["size"] or digest != entry["sha256"] or archive != original:
            raise ValueError("Archive/source changed: " + relative)
        sums[relative] = digest
    for relative, digest in inventory["external_inputs_readback_sha256"].items():
        if sha(ROOT / relative) != digest:
            raise ValueError("External input changed")
    sums["inventory.json"] = EXPECTED["inventory.json"]
    sums["receipt.json"] = EXPECTED["receipt.json"]
    rows = {}
    for line in read(SEAL / "SHA256SUMS").decode().splitlines():
        digest, relative = line.split("  ", 1)
        if relative in rows:
            raise ValueError("Duplicate SUM path")
        rows[relative] = digest
    if rows != sums:
        raise ValueError("Checksum set differs")
    if receipt["PREPARE_or_START_permission"] is not False or receipt["board_tested"] is not False:
        raise ValueError("Helper scope expanded")
    result = {
        "root_fresh_seal_audit_passed": True,
        "seal_files_sha256": EXPECTED,
        "ordinary_archive_files_readback": len(actual_paths),
        "archive_source_copies_byte_equal": True,
        "ordinary_external_inputs_rechecked": 9337, "checksum_rows_rechecked": len(rows),
        "audit_tool_sha256": sha(Path(__file__)),
        "binary_sha256": receipt["binary_sha256"],
        "model_rerun_during_this_audit": False,
        "hardware_operated": False, "PREPARE_or_START_permission": False,
        "timer_boundary": receipt["timer_boundary"],
    }
    OUT.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps({"passed": True, "files": len(actual_paths), "result_sha256": sha(OUT)}))


if __name__ == "__main__":
    main()
