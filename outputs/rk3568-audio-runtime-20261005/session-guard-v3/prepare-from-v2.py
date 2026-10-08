#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create v3 beside the frozen v2; never write old outputs."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'session-guard-v2'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = {}
    for version in ['v1', 'v2']:
        directory = HERE.parent / ('session-guard-' + version)
        listing = directory / 'SHA256SUMS'
        count = 0
        for row in listing.read_text().splitlines():
            expected, name = row.split('  ', 1)
            path = directory / name
            if not path.is_file() or path.is_symlink() or sha(path) != expected:
                raise ValueError('Prior frozen file mismatch: ' + str(path))
            count += 1
        baseline[version] = {'SHA256SUMS_sha256': sha(listing), 'verified_files': count}
    red = json.loads((HERE / 'canonical-red-v2/result.json').read_text())
    if not red['expected_red'] or len(red['targets']) != 3 or any(
            not item['expected_red_reproduced'] or item['cases'] != 13 or item['exit']
            for item in red['targets']):
        raise ValueError('Exact production-name red regression must be reproduced first')
    names = ['audio-session-guard.c', 'guard-parser.h', 'model-driver.c',
             'test-models.py', 'build-freeze.py', 'README.md', 'PLAN.md']
    copied = {}
    for name in names:
        target = HERE / name
        if target.exists():
            raise ValueError('New output already exists: ' + name)
        content = (PRIOR / name).read_bytes()
        if name == 'audio-session-guard.c':
            old = b'canonical_device(argv[4], "fe550000.dma", dma)'
            new = b'canonical_device(argv[4], "fe550000.dmac", dma)'
            if content.count(old) != 1:
                raise ValueError('Need exact one known production site')
            content = content.replace(old, new)
        target.write_bytes(content)
        copied[name] = {'v2_sha256': sha(PRIOR / name), 'v3_initial_sha256': sha(target)}
    (HERE / 'prior-frozen-baseline.json').write_text(json.dumps({
        'board_tested': False, 'prior_versions': baseline,
        'production_diff': 'canonical_device(argv[4], "fe550000.dma", dma) -> fe550000.dmac; exactly one byte inserted',
        'copied_files': copied, 'canonical_red_result_sha256': sha(HERE / 'canonical-red-v2/result.json')
    }, indent=2) + '\n')
    print(json.dumps({'prior_versions_verified': baseline, 'copied': len(copied),
                      'production_source_sha256': sha(HERE / 'audio-session-guard.c')}))


if __name__ == '__main__':
    main()
