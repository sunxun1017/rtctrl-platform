#!/usr/bin/env python3
"""Read-only audit of the public-patch evidence; no build or device actions."""
import hashlib
import json
import stat
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SEALED = HERE / 'sealed-evidence-v1'
OUT = HERE / 'root-audit-v1.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordinary(path, boundary):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Nonordinary evidence: ' + str(path))
    parent = path.parent
    while True:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('Nonordinary ancestor: ' + str(parent))
        if parent == boundary:
            break
        if not parent.is_relative_to(boundary):
            raise ValueError('Evidence escaped boundary')
        parent = parent.parent


if OUT.exists():
    raise ValueError('Fresh root audit required')

inventory_path = SEALED / 'frozen-output-manifest.json'
receipt_path = SEALED / 'receipt.json'
external_path = SEALED / 'external-inputs-union.json'
for path in [inventory_path, receipt_path, external_path]:
    ordinary(path, ROOT)
assert digest(receipt_path) == '242c34350e8d995e98213561423cd4fc99a49cf1bf8f4cfb226f4a50dc20096f'
assert digest(inventory_path) == '4609dcd5a7cfe331f131879dbb618ecd0a8ee76571b2593579bd9efd34616db4'
assert digest(SEALED / 'SHA256SUMS') == 'c30d1f32aee09aabc125680acff95653367343c0904c3b2bd9114d152fde7663'
inventory = json.loads(inventory_path.read_bytes())['files_sha256']
assert len(inventory) == 197
for relative, expected in inventory.items():
    path = SEALED / relative
    ordinary(path, ROOT)
    assert digest(path) == expected, relative

external = json.loads(external_path.read_bytes())
assert len(external) == 42
for relative, expected in external.items():
    path = ROOT / relative
    ordinary(path, ROOT)
    assert digest(path) == expected, relative

sum_rows = (SEALED / 'SHA256SUMS').read_text().splitlines()
assert len(sum_rows) == 198
for row in sum_rows:
    expected, relative = row.split('  ', 1)
    path = SEALED / relative
    ordinary(path, ROOT)
    assert digest(path) == expected, relative

receipt = json.loads(receipt_path.read_bytes())
assert receipt['exit'] == 0
assert receipt['tracked_source_files_verified'] == 89423
assert receipt['actual_v3_ABI_files_verified'] == 2020
assert receipt['new_Image_built'] is False
comparison = receipt['builtin_object_comparisons']['public-built-in']
assert comparison['text_section_equal'] is True
assert comparison['alloc_sections_compared'] == 15
assert comparison['all_alloc_section_bytes_sizes_flags_equal'] is True
assert comparison['objdump_instructions_labels_relocation_markers_equal_after_filename_banner_only'] is True
assert comparison['objects_equal_after_GNU_strip_debug_only'] is True
objects = SEALED / 'executed/builtin/public-built-in'
assert (objects / 'actual-no-debug.o').read_bytes() == (objects / 'public-built-in-no-debug.o').read_bytes()

for name, expected in receipt['new_public_patches_sha256'].items():
    assert digest(ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches' / name) == expected

result = {
    'root_audit_passed': True,
    'root_auditor_sha256': digest(Path(__file__).resolve()),
    'seal_receipt_sha256': digest(receipt_path),
    'ordinary_frozen_files_verified': len(inventory),
    'sum_rows_verified': len(sum_rows),
    'ordinary_external_inputs_verified': len(external),
    'fresh_direct_stripped_object_bytes_equal': True,
    'public_patches_match_seal': True,
    'reported_full_source_replay_and_built_in_Kbuild_receipts_checked': True,
    'full_89423_source_replay_or_Kbuild_rerun_by_this_auditor': False,
    'new_Image_built': False,
    'board_or_network_operated': False,
    'scope': 'Read current ordinary evidence, complete SHA inventories, reported build receipts and exact stripped object bytes; no repeated build or hardware test.',
}
OUT.write_bytes((json.dumps(result, indent=2) + '\n').encode())
print(json.dumps(result))
