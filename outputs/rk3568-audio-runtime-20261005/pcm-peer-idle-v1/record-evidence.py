#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inventory the executed candidate for review; this is deliberately not a seal."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Ordinary evidence required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    result_path = HERE / 'ready-for-review-v1.json'
    if result_path.exists():
        raise ValueError('Fresh review inventory required')
    model = json.loads((HERE / 'models-green-v1/result.json').read_text())
    for name, row in model['results'].items():
        if row['passed'] != row['total'] or sha(HERE / 'models-green-v1' / name / 'wrapped-peer') != row['binary_sha256']:
            raise ValueError('Executed model evidence mismatch')
    production = json.loads((HERE / 'production-v2/manifest.json').read_text())
    if sha(HERE / 'pcm-peer-idle.c') != production['source_sha256'] or \
            sha(HERE / 'production-v2/pcm-peer-idle') != production['binary_sha256'] or \
            sha(HERE / 'models-green-v1/result.json') != production['model_result_sha256']:
        raise ValueError('Current source/binary/model mismatch')
    inputs = json.loads((HERE / 'input-manifest.json').read_text())
    for name, digest in inputs['external_inputs_sha256'].items():
        if sha(ROOT / name) != digest or sha(HERE / 'inputs' / name) != digest:
            raise ValueError('Old protected inputs changed')
    files = {path.relative_to(HERE).as_posix(): sha(path) for path in sorted(HERE.rglob('*')) if path.is_file()}
    record = {'files_sha256': files, 'source_sha256': production['source_sha256'],
              'binary_sha256': production['binary_sha256'], 'old_inputs_unchanged': True,
              'author_offline_execution_complete': True, 'independent_review_completed': False,
              'root_review_completed': False, 'board_tested': False, 'frozen': False,
              'scope': 'Review inventory of immutable input copies, sources, real syscall-boundary executions and static binary; do not interpret as review or board authorization.'}
    with result_path.open('x') as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print(json.dumps({'files': len(files), 'review_inventory_sha256': sha(result_path),
                      'source_sha256': production['source_sha256'], 'binary_sha256': production['binary_sha256'],
                      'frozen': False}, indent=2))


if __name__ == '__main__':
    main()
