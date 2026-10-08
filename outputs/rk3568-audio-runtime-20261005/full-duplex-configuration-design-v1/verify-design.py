#!/usr/bin/env python3
"""Read back design sources/docs and their finite identity references; no tests/build."""
import hashlib
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def metadata(path):
    if not path.is_relative_to(ROOT) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Ordinary file required')
    parent = path.parent
    while True:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('Nonordinary ancestor')
        if parent == ROOT:
            break
        parent = parent.parent
    return {'bytes': path.stat().st_size, 'mode': stat.S_IMODE(path.stat().st_mode),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    manifest_path = HERE / 'input-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if metadata(manifest_path)['sha256'] != 'd00a4bf2c174958ff9271f03f9928095922c4e818bc79d37139081f1b45b7167':
        raise ValueError('Recorded source identity manifest changed')
    originals = {}
    for rel, declared in manifest['inputs'].items():
        expected = {k: declared[k] for k in ['bytes', 'mode', 'sha256']}
        original = ROOT / rel
        if metadata(original) != expected or metadata(HERE / declared['snapshot']) != expected:
            raise ValueError('Design input/source snapshot changed: ' + rel)
        originals[rel] = expected
    for rel, declared in manifest['reference_inputs_not_copied'].items():
        if metadata(ROOT / rel) != declared:
            raise ValueError('Referenced prior evidence changed: ' + rel)
        originals[rel] = declared
    for binding in manifest['source_to_Image_inventory'].values():
        rel = binding['actual_SOURCE']
        if metadata(ROOT / rel) != binding['ordinary']:
            raise ValueError('Finite actual SOURCE changed')
        originals[rel] = binding['ordinary']
    receipt = HERE / 'design-readback.json'
    if receipt.exists() or receipt.is_symlink():
        raise ValueError('Fresh design readback receipt required')
    owned = {}
    for path in sorted(HERE.rglob('*')):
        kind = path.lstat().st_mode
        if stat.S_ISDIR(kind):
            continue
        owned[path.relative_to(HERE).as_posix()] = metadata(path)
    record = {'status': 'DESIGN_EVIDENCE_READBACK_ONLY_NOT_IMPLEMENTATION_ACCEPTANCE',
        'ordinary_owned_inventory': owned, 'finite_original_inputs': originals,
        'ordinary_source_snapshots': len(manifest['inputs']), 'identified_function_bodies_not_executed': 43,
        'model_executed': False, 'build_executed': False, 'board_tested': False,
        'duplex_START_authorized': False, 'production_sources_modified': False,
        'receipt_excluded_from_own_inventory': True}
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    if json.loads(receipt.read_text()) != record:
        raise ValueError('Receipt readback differs')
    print(json.dumps({'ordinary_owned_inventory': len(owned), 'finite_original_inputs': len(originals),
        'receipt_sha256': metadata(receipt)['sha256'],
        'design_sha256': metadata(HERE / 'DESIGN.md')['sha256'],
        'model_plan_sha256': metadata(HERE / 'MODEL-PLAN.md')['sha256']}))


if __name__ == '__main__':
    main()
