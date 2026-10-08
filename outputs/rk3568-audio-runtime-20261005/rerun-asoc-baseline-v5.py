#!/usr/bin/env python3
"""Freshly compile and execute the frozen caller-chain red; no device actions."""
import hashlib
import importlib.util
import json
import stat
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = HERE / 'full-duplex-contract-v1'
MODEL = BASE / 'model-v5'
OUT = HERE / 'build/root-asoc-baseline-v5-v1'
EXPECTED_MANIFEST = 'abfa327867d421e13b39bb7d2f71e25f519f3652cbd0af39b427af577b80c954'
EXPECTED_UNIT = '56e1ba98f4c41052bedf9e8aad9461e430bba90f3d5700c6766181cc27062c34'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Nonordinary input: ' + str(path))
    parent = path.parent
    while parent != ROOT:
        if not parent.is_relative_to(ROOT) or not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('Input ancestry differs')
        parent = parent.parent


if OUT.exists():
    raise ValueError('Fresh output required')
manifest_data = (MODEL / 'input-manifest.json').read_bytes()
assert sha(manifest_data) == EXPECTED_MANIFEST
manifest = json.loads(manifest_data)
assert sha((MODEL / 'unit.c').read_bytes()) == EXPECTED_UNIT
recorded = json.loads((BASE / 'runs-v4/receipt.json').read_bytes())
assert recorded['input_manifest_sha256'] == EXPECTED_MANIFEST
assert recorded['unit_sha256'] == EXPECTED_UNIT
assert recorded['expected_red_confirmed'] is True
util = HERE / 'cpu-lifecycle-v12/source_utils.py'
ordinary(util)
assert sha(util.read_bytes()) == '3d5deab6d6eea70d067c9b0b8336d66f39ce1cc0e18a8a7938a4f60d66c43440'
spec = importlib.util.spec_from_file_location('frozen_source_utils', util)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

sources = {}
for relative, entry in manifest['input_files'].items():
    original = ROOT / relative
    snapshot = BASE / entry['snapshot']
    ordinary(original)
    ordinary(snapshot)
    data = snapshot.read_bytes()
    assert len(data) == entry['size'] and sha(data) == entry['sha256']
    assert original.read_bytes() == data
    sources[original.name] = data.decode()
group_files = {'cpu': 'rockchip_i2s_tdm.c', 'codec': 'rk817_codec.c',
               'dai': 'soc-dai.c', 'component': 'soc-component.c',
               'simple': 'simple-card-utils.c', 'link': 'soc-link.c',
               'pcm': 'soc-pcm.c', 'soc-header': 'soc.h'}
for key, entry in manifest['production_functions'].items():
    group, name = key.split(':', 1)
    body = module.function(sources[group_files[group]], name)
    extracted = module.function((MODEL / ('actual-' + group + '-functions.c')).read_text(), name)
    assert sha(body.encode()) == entry['sha256'] and body == extracted
assert len(manifest['production_functions']) == 57

OUT.mkdir()
snapshot_model = OUT / 'model-v5'
snapshot_model.mkdir()
model_inventory = {}
for path in sorted(MODEL.rglob('*')):
    if path.is_dir():
        continue
    ordinary(path)
    relative = path.relative_to(MODEL)
    destination = snapshot_model / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = path.read_bytes()
    destination.write_bytes(data)
    model_inventory[relative.as_posix()] = {'bytes': len(data), 'sha256': sha(data)}
(OUT / 'model-inventory.json').write_bytes((json.dumps(model_inventory, indent=2) + '\n').encode())
receipt = {'root_fresh_compile_and_execution': True, 'production_functions_verified': 57,
           'input_manifest_sha256': EXPECTED_MANIFEST, 'unit_sha256': EXPECTED_UNIT,
           'root_runner_sha256': sha(Path(__file__).read_bytes()), 'model_only': True,
           'board_tested': False, 'production_changes': False, 'runs': {}}


def run(argv, stem):
    result = subprocess.run(argv, capture_output=True, timeout=45)
    (OUT / (stem + '.stdout')).write_bytes(result.stdout)
    (OUT / (stem + '.stderr')).write_bytes(result.stderr)
    return result, {'argv': argv, 'exit': result.returncode,
                    'stdout_sha256': sha(result.stdout), 'stderr_sha256': sha(result.stderr)}


for label, entry in recorded['runs'].items():
    binary = OUT / ('caller-chain-' + label)
    compile_argv = list(entry['compile']['argv'])
    compile_argv[compile_argv.index(str(MODEL / 'unit.c'))] = str(snapshot_model / 'unit.c')
    compile_argv[compile_argv.index('-o') + 1] = str(binary)
    compiled, compile_record = run(compile_argv, label + '-compile')
    assert compiled.returncode == 0 and not compiled.stderr
    execute_argv = list(entry['execution']['argv'])
    execute_argv[-1] = str(binary)
    executed, execute_record = run(execute_argv, label)
    lines = executed.stdout.decode().splitlines()
    failures = [line.split()[1] for line in lines
                if line.startswith('CONTRACT_CHECK ') and line.endswith(' 0')]
    boundary_failures = [line for line in lines
                         if line.startswith('BOUNDARY_CHECK ') and line.endswith(' 0')]
    counts = json.loads(lines[-1])
    assert executed.returncode == 1 and not executed.stderr
    assert failures == recorded['expected_business_failures'] and not boundary_failures
    assert counts == {'contract_total': 25, 'contract_passed': 0,
                      'boundary_total': 76, 'boundary_passed': 76}
    receipt['runs'][label] = {'compile': compile_record, 'execution': execute_record,
                             'binary_sha256': sha(binary.read_bytes()),
                             'counts': counts, 'exact_expected_red': True}
    (OUT / 'result.json').write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
receipt['all_three_environments_reproduced_exact_red'] = True
(OUT / 'result.json').write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
print(json.dumps({'production_functions_verified': 57, 'runs': {label: entry['counts']
                  for label, entry in receipt['runs'].items()}, 'model_only': True}))
