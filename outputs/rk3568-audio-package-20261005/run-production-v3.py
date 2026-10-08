#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the unchanged production CLI interface and retain exact offline receipts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def metadata(path):
    data = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}


def write_new(path, value):
    with path.open('xb') as stream:
        stream.write(value)


def main():
    output = HERE / 'build/production-cli-v3'
    output.mkdir(exist_ok=False)
    gate = 'outputs/rk3568-audio-runtime-20261005/build/review-gate-v3.json'
    package = 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3'
    audit = 'outputs/rk3568-audio-package-20261005/build/audit-production-v3'
    commands = [
        ('build', [sys.executable, '-B', str(HERE / 'build-audio-package-v3.py'),
                   '--review-gate', gate, '--out', package]),
        ('audit', [sys.executable, '-B', str(HERE / 'audit-audio-package-v3.py'),
                   '--review-gate', gate, '--candidate', package, '--out', audit]),
    ]
    results = []
    for name, argv in commands:
        started = time.monotonic()
        process = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=600)
        write_new(output / (name + '.stdout'), process.stdout)
        write_new(output / (name + '.stderr'), process.stderr)
        receipt = {'name': name, 'argv': argv, 'exit_code': process.returncode,
                   'elapsed_seconds': round(time.monotonic() - started, 6),
                   'stdout': metadata(output / (name + '.stdout')),
                   'stderr': metadata(output / (name + '.stderr'))}
        results.append(receipt)
        write_new(output / (name + '.json'), (json.dumps(receipt, indent=2) + '\n').encode())
        if process.returncode != 0:
            print(process.stderr.decode('utf-8', 'replace'))
            raise SystemExit(process.returncode)
    result = {'status': 'RAM_ONLY_NOT_FLASH_READY', 'commands': results,
              'inputs': [metadata(ROOT / gate),
                         metadata(ROOT / 'outputs/rk3568-audio-runtime-20261005/build/integration-v2/Image'),
                         metadata(ROOT / 'outputs/rk3568-audio-runtime-20261005/build/integration-v2/manifest.json')],
              'package_manifest': metadata(ROOT / package / 'manifest.json'),
              'package_receipt': metadata(ROOT / package / 'receipt.json'),
              'audit_receipt': metadata(ROOT / audit / 'receipt.json'),
              'board_tested': False, 'deployed': False, 'formal_flash_ready': False}
    write_new(output / 'result.json', (json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps({'status': result['status'],
                      'commands': [{'name': item['name'], 'exit_code': item['exit_code']} for item in results]}, indent=2))


if __name__ == '__main__':
    main()
