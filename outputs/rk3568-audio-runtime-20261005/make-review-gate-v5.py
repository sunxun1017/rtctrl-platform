#!/usr/bin/env python3
"""Re-read accepted offline evidence and bind the next private Image inputs."""
import hashlib
import json
import os
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = HERE / "asoc-open-rollback-v1"
PUBLIC = HERE / "public-integration-v1/sealed-evidence-v1"
OUT = HERE / "build/review-gate-v5.json"
AUDIT = HERE / "build/root-asoc-seal-audit-v1.json"
EXPECTED = {
    CORE / "sealed-v1/receipt.json": "bdcdb5081a0a770413d48fcfc839121ced7bceb32204c725dea1ec5351d7adf6",
    CORE / "sealed-v1/file-manifest.json": "b22e81e766943c704e0a55c84785aad00cd18295189d417e815d804a8bae3f14",
    CORE / "sealed-v1/SHA256SUMS": "d92dfebd958819ce7b36f9fbcbb60d0a3df644f5545fc5788c72a31f470304da",
    PUBLIC / "receipt.json": "242c34350e8d995e98213561423cd4fc99a49cf1bf8f4cfb226f4a50dc20096f",
    PUBLIC / "frozen-output-manifest.json": "4609dcd5a7cfe331f131879dbb618ecd0a8ee76571b2593579bd9efd34616db4",
    PUBLIC / "SHA256SUMS": "c30d1f32aee09aabc125680acff95653367343c0904c3b2bd9114d152fde7663",
    HERE / "build/review-gate-v4.json": "181786c4a71065614f744ad609a0dc1a2c3a0dff0eaea21cda3a9fb319faf55d",
    HERE / "build-audio-image-v4.py": "4110837528a3d2e4dac6b9f26e98849944dec5c72241fd9ad6eef05bba135a41",
    HERE / "REVIEW-ASOC-OPEN-ROLLBACK-20261006.md": "2cc2ead8e92ed9c2119e30bc518c9f384080627f916f0e8d493b1439ac52f38c",
}


def ordinary(path):
    if not path.is_relative_to(ROOT) or ".." in path.parts:
        raise ValueError("Input escaped repository")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Nonordinary input: " + str(path))
    for ancestor in path.parents:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError("Nonordinary ancestry: " + str(ancestor))
        if ancestor == ROOT:
            break
    return path.read_bytes()


def sha(path):
    return hashlib.sha256(ordinary(path)).hexdigest()


def write(path, value):
    path.write_bytes((json.dumps(value, indent=2) + "\n").encode())


def check_sums(path, expected):
    rows = {}
    for line in ordinary(path).decode().splitlines():
        digest, relative = line.split("  ", 1)
        if relative in rows:
            raise ValueError("Duplicate SUM path")
        rows[relative] = digest
    if rows != expected:
        raise ValueError("SUM set or hash differs")
    return len(rows)


def main():
    if OUT.exists() or AUDIT.exists():
        raise ValueError("Fresh gate and audit outputs required")
    bound = {}

    def bind(path, expected=None):
        digest = sha(path)
        if expected is not None and digest != expected:
            raise ValueError("Changed reviewed input: " + str(path))
        relative = path.relative_to(ROOT).as_posix()
        if relative in bound and bound[relative] != digest:
            raise ValueError("Conflicting binding")
        bound[relative] = digest
        return digest

    for path, digest in EXPECTED.items():
        bind(path, digest)
    old = json.loads(ordinary(HERE / "build/review-gate-v4.json"))
    if old["accepted_for_offline_integration"] is not True:
        raise ValueError("Old CPU/C3 gate not accepted")
    for relative, digest in old["files_sha256"].items():
        bind(ROOT / relative, digest)
    core_inventory = json.loads(ordinary(CORE / "sealed-v1/file-manifest.json"))["files_sha256"]
    if len(core_inventory) != 4357:
        raise ValueError("Incomplete core seal inventory")
    for relative, digest in core_inventory.items():
        bind(CORE / relative, digest)
    live = set()
    for path in CORE.rglob("*"):
        if path.is_relative_to(CORE / "sealed-v1"):
            continue
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        ordinary(path)
        live.add(path.relative_to(CORE).as_posix())
    if live != set(core_inventory):
        raise ValueError("Core live inventory differs from seal")
    core_sum = check_sums(CORE / "sealed-v1/SHA256SUMS", {
        **core_inventory,
        "sealed-v1/file-manifest.json": sha(CORE / "sealed-v1/file-manifest.json")})
    external = json.loads(ordinary(CORE / "freeze-preflight-v1/external-inputs.json"))
    if len(external["regular_files_sha256"]) != 8488 or len(external["SDK_internal_links"]) != 4:
        raise ValueError("Incomplete core external input set")
    for relative, digest in external["regular_files_sha256"].items():
        bind(ROOT / relative, digest)
    checked_links = {}
    sdk_source = ROOT / ".deps/kernel-source/aiot-3568pq-audio-v3"
    for relative, entry in external["SDK_internal_links"].items():
        path = ROOT / relative
        for ancestor in path.parents:
            if not stat.S_ISDIR(ancestor.lstat().st_mode):
                raise ValueError("SDK link ancestry changed")
            if ancestor == ROOT:
                break
        if not stat.S_ISLNK(path.lstat().st_mode) or os.readlink(path) != entry["link_target"]:
            raise ValueError("SDK internal link changed")
        target = sdk_source / entry["resolved_relative"]
        if path.resolve(strict=True) != target or sha(target) != entry["resolved_sha256"]:
            raise ValueError("SDK link resolved input changed")
        bind(target, entry["resolved_sha256"])
        checked_links[relative] = entry
    public_inventory = json.loads(ordinary(PUBLIC / "frozen-output-manifest.json"))["files_sha256"]
    if len(public_inventory) != 197:
        raise ValueError("Incomplete public seal inventory")
    for relative, digest in public_inventory.items():
        bind(PUBLIC / relative, digest)
    public_sum = check_sums(PUBLIC / "SHA256SUMS", {
        **public_inventory, "frozen-output-manifest.json": sha(PUBLIC / "frozen-output-manifest.json")})
    public_external = json.loads(ordinary(PUBLIC / "external-inputs-union.json"))
    for relative, digest in public_external.items():
        bind(ROOT / relative, digest)
    extra = [
        "public-integration-v1/independent-review-v1.json",
        "build/root-asoc-candidate-v2/result.json", "rerun-asoc-candidate-v2.py",
        "prepare-audio-v4-source.py", "build/source-preparation-v4/result.json",
        "check-image-builder-v4-preflight.py",
        "build/image-builder-v4-preflight-v1/result.json",
        "build/image-builder-v4-preflight-v1/independent-review.json",
        "make-review-gate-v5.py",
    ]
    for relative in extra:
        bind(HERE / relative)
    root_result = json.loads(ordinary(HERE / "build/root-asoc-candidate-v2/result.json"))
    public_review = json.loads(ordinary(HERE / "public-integration-v1/independent-review-v1.json"))
    if root_result["root_fresh_compile_and_execution"] is not True or root_result["all_six_fresh_compiles_and_runs_match"] is not True:
        raise ValueError("Root fresh model execution not complete")
    for version, passed in [("red", 0), ("green", 21)]:
        runs = root_result["versions"][version]["runs"]
        if len(runs) != 3:
            raise ValueError("Three actual model environments required")
        for run in runs.values():
            if run["counts"] != {"contract_total": 25, "contract_passed": passed,
                                 "boundary_total": 110, "boundary_passed": 110}:
                raise ValueError("Root model count changed")
            if run["compile"]["exit"] != 0 or run["execution"]["exit"] != 1:
                raise ValueError("Root model exit changed")
    if public_review["accepted"] is not True:
        raise ValueError("Public independent review not accepted")
    # Counts are evidence scope, never permission for duplex START.
    audit = {
        "root_fresh_seal_audit_passed": True,
        "ordinary_core_files_verified": len(core_inventory), "core_SUM_rows_verified": core_sum,
        "ordinary_core_external_inputs_verified": 8488,
        "SDK_internal_links_verified_separately": checked_links,
        "public_files_verified": len(public_inventory), "public_SUM_rows_verified": public_sum,
        "public_external_inputs_verified": len(public_external),
        "independent_core_seal_reviewer": "/root/battery_dt_audit_1006",
        "independent_core_seal_review_accepted": True,
        "root_acceptance_note_sha256": sha(HERE / "REVIEW-ASOC-OPEN-ROLLBACK-20261006.md"),
        "root_result_sha256": sha(HERE / "build/root-asoc-candidate-v2/result.json"),
        "root_model_rerun_during_this_inventory_audit": False,
        "ordinary_bound_input_count": len(bound), "audit_tool_sha256": sha(Path(__file__)),
        "full_Image_built": False, "hardware_operated": False, "duplex_START_allowed": False,
    }
    write(AUDIT, audit)
    bind(AUDIT)
    prefix = HERE.relative_to(ROOT).as_posix()
    gate = {**old,
        "supersedes": prefix + "/build/review-gate-v4.json",
        "accepted_for_offline_integration": True,
        "asoc_independent_review_completed": True,
        "asoc_root_fresh_models_completed": True,
        "asoc_actual_Kbuild_completed": True,
        "public_14_integration_review_completed": True,
        "review_mode": "Independent core source/model/Kbuild/seal and public-14 review, plus root fresh model and seal readback",
        "files_sha256": dict(sorted(bound.items())),
        "SDK_internal_links": checked_links,
        "asoc_source_manifest": prefix + "/asoc-open-rollback-v1/source-manifest-v1.json",
        "asoc_patch": prefix + "/asoc-open-rollback-v1/candidate-v1.patch",
        "asoc_source_directory": prefix + "/asoc-open-rollback-v1/source-v1",
        "public_tracked_source_inventory": prefix + "/public-integration-v1/sealed-evidence-v1/executed/public-replay/source/tracked-source-inventory.json",
        "public_patch_count": 14, "private_ASoC_patch_count": 1,
        "asoc_contract_passed": 21, "asoc_contract_total": 25,
        "asoc_boundary_observations_passed": 110, "asoc_boundary_unique_labels": 74,
        "compressed_branch_Kconfig_generated": False, "compressed_branch_ABI_validated": False,
        "board_start_allowed": False, "duplex_START_allowed": False,
        "full_image_built": False, "codec_abi_verified": False,
        "hardware_operated": False, "formal_flash_ready": False,
    }
    write(OUT, gate)
    print(json.dumps({"gate_sha256": sha(OUT), "files": len(bound),
                      "root_seal_audit_sha256": sha(AUDIT), "Image_built": False}))


if __name__ == "__main__":
    main()
