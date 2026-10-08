#!/usr/bin/env python3
"""Record the independent read-only review without changing sealed evidence."""
import hashlib
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = HERE / "public-integration-v1"
EXPECTED = {
    "sealed-evidence-v1/receipt.json": "242c34350e8d995e98213561423cd4fc99a49cf1bf8f4cfb226f4a50dc20096f",
    "root-audit-v1.py": "e17733902adbf8579d7c1a23c67302195cd7b5285869583d3d8ef7a572b7a3dc",
    "verification-v1/receipt.json": "8ea1b85795dd79ff13248d7d2f230eddef8c088ee77b06629eaae61ceac04bf6",
}


def ordinary(path):
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise RuntimeError(f"symlink rejected: {ancestor}")
        if ancestor == ROOT:
            break
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RuntimeError(f"not ordinary: {path}")
    return path.read_bytes()


def main():
    destination = PUBLIC / "independent-review-v1.json"
    if destination.exists():
        raise RuntimeError("review record already exists")
    inputs = {}
    for relative, digest in EXPECTED.items():
        data = ordinary(PUBLIC / relative)
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise RuntimeError(f"changed input: {relative}")
        inputs[relative] = {"bytes": len(data), "sha256": actual}
    audit_bytes = ordinary(PUBLIC / "root-audit-v1.json")
    audit = json.loads(audit_bytes)
    assert audit["root_audit_passed"]
    assert audit["ordinary_frozen_files_verified"] == 197
    assert audit["sum_rows_verified"] == 198
    assert audit["ordinary_external_inputs_verified"] == 42
    assert audit["fresh_direct_stripped_object_bytes_equal"]
    seal = json.loads(ordinary(PUBLIC / "sealed-evidence-v1/receipt.json"))
    comparison = seal["builtin_object_comparisons"]["public-built-in"]
    assert comparison["all_alloc_section_bytes_sizes_flags_equal"]
    assert comparison["alloc_sections_compared"] == 15
    assert comparison["objects_equal_after_GNU_strip_debug_only"]
    inputs["root-audit-v1.json"] = {
        "bytes": len(audit_bytes), "sha256": hashlib.sha256(audit_bytes).hexdigest()
    }
    result = {
        "date": "2026-10-06",
        "independent_reviewer": "/root/battery_dt_audit_1006",
        "root_recording_tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "accepted": True,
        "blocking_findings": [],
        "inputs_rechecked_by_recording_tool": inputs,
        "independent_read_only_checks": {
            "ordinary_frozen_files": 197, "SUM_rows": 198, "external_references": 42,
            "actual_ABI_files": 2020, "old_v11_v12_addendum_files": [2251, 2289, 128],
            "SDK_clean_and_pinned_commit_verified": True,
            "two_public_diff_suffixes_exact_frozen_deltas": True,
            "all_28_check_apply_exit_codes_zero": True,
            "complete_tracked_source_inventory_rows_examined": 89423,
            "recorded_complete_inventory_comparison_and_23_changes_verified": True,
            "actual_builtin_argv_and_CC_source_not_MODULE_verified": True,
            "all_15_alloc_sections_and_text_equal": True,
            "objdump_equal_after_filename_banner_only": True,
            "GNU_strip_debug_whole_objects_equal": True,
            "only_debug_line_str_and_two_debug_relocations_differ_unstripped": True,
            "old_obj_m_difference_and_first_PATH_failure_kept": True
        },
        "scope": "Public patch identity, recorded full source replay, actual-target single built-in object and closed SHA evidence set.",
        "source_replay_or_Kbuild_rerun_by_reviewer": False,
        "new_Image_built": False,
        "behavior_models_rerun": False,
        "hardware_operated": False,
        "full_duplex_validated": False,
        "formal_flash_validated": False
    }
    destination.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"accepted": True, "record": str(destination),
                      "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
