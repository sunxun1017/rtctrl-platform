#!/usr/bin/env python3
"""Run one fresh offline package audit with reviewed, explicit input identities."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = HERE / 'audio-package-v5.py'
GATE = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/review-gate-v5.json'
CANDIDATE = HERE / 'build/ram-audio-v5'
OUT = HERE / 'build/audit-root-v5'
CLI = HERE / 'build/audit-root-cli-v5-r2'
CORE_SHA = '8857237d9dbbf8022cd0cd0b26c630da4caee3c615a47015de244e7434b2b45c'
GATE_SHA = 'b5a3de60be520d78b4f48a5bfcf6971b81241385e22e8fe5913336d9ecf580c4'


def sha(path):
    for component in [path, *path.parents]:
        if component == ROOT:
            break
        if component.is_symlink():
            raise ValueError('Ordinary input required: ' + str(component))
    if not path.is_file():
        raise ValueError('File required: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path):
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def candidate_files():
    paths = []
    for path in CANDIDATE.rglob('*'):
        if path.is_symlink():
            raise ValueError('Package link rejected: ' + str(path))
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Package special file rejected: ' + str(path))
        paths.append(path)
    return sorted(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--package-receipt-sha256', required=True)
    args = parser.parse_args()
    expected = {
        CORE: CORE_SHA,
        GATE: GATE_SHA,
        CANDIDATE / 'manifest.json': args.manifest_sha256,
        CANDIDATE / 'receipt.json': args.package_receipt_sha256,
    }
    for path, value in expected.items():
        if not re.fullmatch('[0-9a-f]{64}', value) or sha(path) != value:
            raise ValueError('Reviewed input identity differs: ' + str(path))
    if any(path.exists() or path.is_symlink() for path in [CLI, OUT]):
        raise ValueError('Fresh root audit outputs required')
    paths = candidate_files()
    before = {p.relative_to(ROOT).as_posix(): identity(p) for p in paths}
    before.update({p.relative_to(ROOT).as_posix(): identity(p) for p in [CORE, GATE]})
    CLI.mkdir()
    (CLI / 'runner-snapshot.py').write_bytes(Path(__file__).read_bytes())
    argv = [sys.executable, '-B', str(CORE), 'audit', '--review-gate', GATE.relative_to(ROOT).as_posix(),
            '--candidate', str(CANDIDATE), '--out', str(OUT)]
    started = time.monotonic()
    with (CLI / 'stdout').open('xb') as stdout, (CLI / 'stderr').open('xb') as stderr:
        run = subprocess.run(argv, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=1200)
    after = {name: identity(ROOT / name) for name in before}
    current_paths = candidate_files()
    record = {
        'mode': 'ROOT_FRESH_PACKAGE_AUDIT_ONLY', 'argv': argv, 'exit_code': run.returncode,
        'elapsed_seconds': round(time.monotonic() - started, 6),
        'stdout': identity(CLI / 'stdout'), 'stderr': identity(CLI / 'stderr'),
        'inputs_before': before, 'inputs_after': after,
        'input_keyset_unchanged': paths == current_paths,
        'input_bytes_unchanged': before == after,
        'runner_sha256': sha(Path(__file__)),
        'board_tested': False, 'PREPARE_or_START_permission': False,
        'full_audio_adaptation_completed': False, 'formal_flash_ready': False,
    }
    if (OUT / 'receipt.json').is_file():
        record['audit_receipt'] = identity(OUT / 'receipt.json')
    (CLI / 'result.json').write_bytes((json.dumps(record, indent=2) + '\n').encode())
    if run.returncode or before != after or paths != current_paths:
        raise ValueError('Fresh root audit failed; evidence preserved')
    print(json.dumps({'exit_code': run.returncode, 'candidate_files': len(paths),
                      'inputs_unchanged': True, 'receipt': record['audit_receipt'],
                      'board_tested': False}))


if __name__ == '__main__':
    main()
