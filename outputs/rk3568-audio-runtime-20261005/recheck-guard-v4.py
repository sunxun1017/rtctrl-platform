#!/usr/bin/env python3
"""Root frozen-ELF reexecution of new production clock-stage models."""
from pathlib import Path
import hashlib
import json
import subprocess
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GUARD = HERE / 'session-guard-v4'
OUT = HERE / 'build/guard-v4-root-recheck-v1'
OUT.mkdir(exist_ok=False)
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
count = 0
for line in (GUARD / 'SHA256SUMS').read_text().splitlines():
    expected, name = line.split('  ', 1)
    assert sha(GUARD / name) == expected, name
    count += 1
assert count == 685, count
author = json.loads((GUARD / 'clock-stage-models/result.json').read_text())
rows = []
for item in author['targets']:
    target = item['target']
    binary = GUARD / ('clock-stage-models/clock-stage-' + target)
    assert sha(binary) == item['binary_sha256']
    argv = ([str(ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static')]
            if target == 'aarch64-qemu' else []) + [str(binary)]
    actual = subprocess.run(argv, capture_output=True, timeout=60)
    (OUT / (target + '.stdout')).write_bytes(actual.stdout)
    (OUT / (target + '.stderr')).write_bytes(actual.stderr)
    lines = actual.stdout.decode().splitlines()
    answers = dict(line.split() for line in lines)
    failed = [key for key, value in answers.items() if value != '1']
    row = {'target': target, 'argv': argv, 'reused_frozen_binary': True,
           'binary_sha256': sha(binary), 'cases': len(lines), 'failed': failed,
           'exit_code': actual.returncode, 'stdout_sha256': sha(OUT / (target + '.stdout')),
           'stderr_sha256': sha(OUT / (target + '.stderr'))}
    rows.append(row)
    assert len(lines) == len(answers) == 288 and not failed and actual.returncode == 0, row
    assert row['stdout_sha256'] == item['stdout_sha256']
    assert row['stderr_sha256'] == item['stderr_sha256']
record = {'model_only': True, 'board_tested': False, 'start_allowed': False,
          'recompiled': False, 'inventory_verified': count, 'targets': rows,
          'scope': 'Actual main-to-first-collect clock/parent gates; intentionally fails later proc/devices; not complete collector success'}
(OUT / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
