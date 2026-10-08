#!/usr/bin/env python3
"""Root reexecution of the frozen v2 UIO parser cases, not board evidence."""
from pathlib import Path
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GUARD = HERE / 'session-guard-v2'
OUT = HERE / 'build/guard-v2-root-recheck-v1'
OUT.mkdir(exist_ok=False)
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
inventory = []
for line in (GUARD / 'SHA256SUMS').read_text().splitlines():
    digest, name = line.split('  ', 1)
    path = GUARD / name
    assert sha(path) == digest, name
    inventory.append({'path': name, 'sha256': digest})
assert len(inventory) == 1128
lines = [line for line in (GUARD / 'models/cases.txt').read_text().splitlines()
         if line.startswith(('devices-', 'uio-fd-', 'registered-fd-'))]
assert len(lines) == 61, len(lines)
listing = OUT / 'cases.txt'
listing.write_text('\n'.join(lines) + '\n')
names = [line.split()[0] for line in lines]
expected = dict(line.split() for line in (GUARD / 'models/host.stdout').read_text().splitlines())
results = []
for target, prefix in [('host', []), ('asan-ubsan', []),
                       ('aarch64-qemu', [str(ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static')])]:
    binary = GUARD / ('models/model-' + target)
    argv = prefix + [str(binary), str(listing)]
    result = subprocess.run(argv, capture_output=True, timeout=60)
    (OUT / (target + '.stdout')).write_bytes(result.stdout)
    (OUT / (target + '.stderr')).write_bytes(result.stderr)
    actual = dict(line.split() for line in result.stdout.decode().splitlines())
    failures = [name for name in names if actual.get(name) != expected[name]]
    results.append({'target': target, 'argv': argv, 'binary_sha256': sha(binary),
                    'cases': len(names), 'failures': failures, 'exit_code': result.returncode,
                    'stdout_sha256': sha(OUT / (target + '.stdout')),
                    'stderr_sha256': sha(OUT / (target + '.stderr'))})
    assert result.returncode == 0 and not failures, results[-1]
record = {'model_only': True, 'board_tested': False, 'start_allowed': False,
          'inventory_verified': len(inventory), 'inventory_sha256': sha(GUARD / 'SHA256SUMS'),
          'reused_frozen_binaries': True, 'targets': results}
(OUT / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
