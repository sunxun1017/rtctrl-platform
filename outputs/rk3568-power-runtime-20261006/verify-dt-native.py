#!/usr/bin/env python3
"""Verify full DT metadata and bind preserved same-input DTC evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'build/dtb-v2'
BASE = ROOT / 'outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb'
PRIOR = ROOT / 'outputs/rk3568-formal-dtb-20261005/build/emmc-v1'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

spec = importlib.util.spec_from_file_location('semantics', ROOT / 'outputs/rk3568-boot-package-20261005/dt-semantics-v2.py')
semantic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(semantic)
evidence = json.loads((OUT / 'result.json').read_text())
prior = json.loads((PRIOR / 'manifest.json').read_text())
assert sha(BASE) == prior['baseline_sha256'] == evidence['baseline_sha256']
assert prior['dtc_sha256'] == evidence['dtc_sha256']
assert sha(ROOT / '.deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc') == evidence['dtc_sha256']
for rel in ('outputs/rk3568-boot-package-20261005/dt-semantics-v2.py', 'outputs/rk3568-boot-package-20261005/libfdt-v2.py'):
    assert sha(ROOT / rel) == prior['inputs_sha256'][rel]
assert sha(PRIOR / 'audio-baseline.dtb') == sha(BASE)
baseline_stderr = (PRIOR / 'dtc/baseline-decode.stderr').read_bytes()
baseline_run = next(row for row in prior['dtc_runs'] if row['stage'] == 'baseline-decode')
assert hashlib.sha256(baseline_stderr).hexdigest() == baseline_run['stderr_sha256']
assert baseline_run['exit_code'] == 0
candidate_stderr = (OUT / 'dtc-stderr.txt').read_bytes()
props = json.loads((OUT / 'original-properties.json').read_text())
node = props['node']
before = semantic.parse(BASE.read_bytes())
original = semantic.parse((HERE / 'original-v1/android-original.dtb').read_bytes())
assert props['properties_hex'] == {key[len(node)+1:]: value for key, value in original['properties'].items() if key.startswith(node + ':')}
expected = dict(before['properties'])
expected.update({node + ':' + key: value for key, value in props['properties_hex'].items()})
checks = {'original_16_properties_exact': len(props['properties_hex']) == 16,
          'same_dtc_same_base_preserved_warning_evidence': baseline_stderr == candidate_stderr}
for i in range(1, 4):
    target = OUT / f'audio-battery-{i}.dtb'
    after = semantic.parse(target.read_bytes())
    checks[f'run{i}_sha_equal'] = sha(target) == evidence['candidate_sha256']
    checks[f'run{i}_one_node_added'] = set(after['nodes']) == set(before['nodes']) | {node}
    checks[f'run{i}_all_properties_exact'] = after['properties'] == expected
    checks[f'run{i}_phandles_equal'] = semantic.phandles(before) == semantic.phandles(after)
    for key in ('reservations', 'boot_cpuid', 'version', 'last_compatible_version'):
        checks[f'run{i}_{key}_equal'] = before[key] == after[key]
report = {'passed': all(checks.values()), 'checks': checks,
          'method': 'native pure DT parser plus SHA-bound previously executed same-base same-DTC diagnostic; no fresh DTC invocation in this verification',
          'preserved_baseline_manifest_sha256': sha(PRIOR / 'manifest.json'),
          'baseline_stderr_sha256': hashlib.sha256(baseline_stderr).hexdigest(),
          'candidate_stderr_sha256': hashlib.sha256(candidate_stderr).hexdigest(),
          'warning_bytes': len(candidate_stderr), 'board_tested': False}
(OUT / 'baseline-dtc-stderr-preserved.txt').write_bytes(baseline_stderr)
(OUT / 'baseline-dtc-manifest-preserved.json').write_bytes((PRIOR / 'manifest.json').read_bytes())
(OUT / 'verification-native-v1.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
assert report['passed']
