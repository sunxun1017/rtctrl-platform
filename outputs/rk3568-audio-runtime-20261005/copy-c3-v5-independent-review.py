#!/usr/bin/env python3
"""Preserve the unfinished independent review and its reproduced blocker."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
SOURCE = Path('/tmp/rtctrl-c3-independent-review-toja28_c')
DEST = HERE / 'build/c3-v5-independent-review'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if DEST.exists():
        raise ValueError('Fresh evidence destination required')
    paths = sorted(p for p in SOURCE.rglob('*') if p.is_file())
    if any(p.is_symlink() or not p.resolve().is_relative_to(SOURCE) for p in paths):
        raise ValueError('Ordinary source evidence required')
    model = json.loads((SOURCE / 'independent-model/result.json').read_text())
    production = json.loads((SOURCE / 'production-recompile/result.json').read_text())
    if production['source_manifest'] != '0cc48150995c765d81a2004aaf23373cab0ae76c156ae62517324deb32ad67ea':
        raise ValueError('Unexpected candidate manifest')
    expected_probe = {'host': -11, 'host-sanitized': 1, 'aarch64': -11}
    for name, code in expected_probe.items():
        cases = model['runs'][name]['cases']
        if cases['probe-irq']['exit'] != code or any(v['exit'] for k, v in cases.items() if k != 'probe-irq'):
            raise ValueError('Independent reproduction differs')
    inventory = {str(p.relative_to(SOURCE)): sha(p) for p in paths}
    DEST.mkdir(parents=True)
    for name, expected in inventory.items():
        dst = DEST / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, dst)
        if sha(dst) != expected or sha(SOURCE / name) != expected:
            raise ValueError('Evidence changed during copy: ' + name)
    record = {
        'review_completed': False,
        'candidate_rejected': True,
        'source_manifest_sha256': production['source_manifest'],
        'production_recompile_passed': production['passed'],
        'image_built': production['image_built'],
        'files_verified': len(inventory),
        'files_sha256': inventory,
        'probe_irq_exit_by_environment': expected_probe,
        'boundary': model['boundary'],
    }
    (DEST / 'inventory.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({k: v for k, v in record.items() if k != 'files_sha256'}))


if __name__ == '__main__':
    main()
