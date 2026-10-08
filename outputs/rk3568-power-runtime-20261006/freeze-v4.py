#!/usr/bin/env python3
"""Bind already executed evidence to exact bytes; no Linux or board action."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'sealed-v4'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

source = HERE / 'candidate-v4/drivers/power/supply/rk817_battery.c'
patch = HERE / 'candidate-v4/rk817-lifecycle-review.patch'
kbuild = HERE / 'build/kbuild-v5'
dt = HERE / 'build/dtb-v2'
identities = {
    'production_source': (source, '60214a61168143700b06e9f2aad08697ef6be6f2181d9b8a427336aa10709efc'),
    'local_patch': (patch, '49adf6d5a0393d3434cfa24be68b9707b30d013efdb39cadd23db1403f352e3d'),
    'kbuild_config': (kbuild / 'battery.config', 'f79826d4993b1fe236094af2da4df0d91ea4cc93459df710c66c602c132a93c9'),
    'kbuild_object': (kbuild / 'battery.o', '40206d37b74a67a8b8012b2aaebcfed94be12bd9c23cb09b87a44f09f875d92d'),
    'dt_candidate': (dt / 'audio-battery-1.dtb', 'b44e479e8d346e866f2fef86704215354b7b7bc521c7f2ce43c6de50e7400684'),
}
for path, expected in identities.values():
    assert sha(path) == expected, str(path)

original = read(HERE / 'original-v1/manifest.json')
assert len(original['files_sha256']) == 15
for rel, expected in original['files_sha256'].items():
    assert sha(HERE / 'original-v1' / rel) == expected, rel
kb = read(kbuild / 'manifest.json')
assert len(kb['steps']) == 32 and all(row['returncode'] == 0 for row in kb['steps'])
assert not kb['image_built'] and not kb['board_tested'] and not kb['external_chargers_enabled']
for key, role in [('source_sha256','production_source'), ('patch_sha256','local_patch'), ('config_sha256','kbuild_config'), ('object_sha256','kbuild_object')]:
    assert kb[key] == identities[role][1]
assert sha(kbuild / 'kernel-source/drivers/power/supply/rk817_battery.c') == sha(source)
assert sha(kbuild / 'kernel-build/drivers/power/supply/rk817_battery.o') == identities['kbuild_object'][1]
assert sha(kbuild / 'kernel-build/.config') == identities['kbuild_config'][1]
assert len(kb['baseline_patches_sha256']) == 12
for rel, expected in kb['baseline_patches_sha256'].items():
    assert sha(ROOT / rel) == expected, rel

def config_values(path):
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
            values[line[2:-11]] = 'n'
    return values

baseline = config_values(HERE / 'original-v1/audio.config')
candidate = config_values(kbuild / 'battery.config')
delta = {key: [baseline.get(key), candidate.get(key)] for key in baseline.keys() | candidate.keys() if baseline.get(key) != candidate.get(key)}
assert delta == {'CONFIG_BATTERY_RK817': ['n','y'], 'CONFIG_CHARGER_BQ24735': ['y','n']}, delta
for key, value in candidate.items():
    if key == 'CONFIG_CHARGER_RK817' or key.startswith('CONFIG_CHARGER_BQ'):
        assert value == 'n', (key, value)

spec = importlib.util.spec_from_file_location('extractor', HERE / 'test-model.py')
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)
source_text = source.read_text()
sequential_dir = HERE / 'build/green-v4'
threaded_dir = HERE / 'build/threaded-green-v4'
seq = read(sequential_dir / 'result.json')
threads = read(threaded_dir / 'result.json')
assert seq['source_sha256'] == threads['production_source_sha256'] == sha(source)
assert len(seq['units_sha256']) == 32
sequence_wrapper = (sequential_dir / 'wrapper.c').read_text()
thread_wrapper = (threaded_dir / 'wrapper.c').read_text()
units = {}
for name, expected in seq['units_sha256'].items():
    unit = extractor.block(source_text, r'^static[^\n;{}]*\b' + name + r'\s*\([^;{}]*?\)\s*(?=\{)')
    units[name] = hashlib.sha256(unit.encode()).hexdigest()
    assert units[name] == expected and unit in sequence_wrapper and unit in thread_wrapper, name
structure_hashes = {}
for name in ('battery_platform_data','rk817_battery_device'):
    unit = extractor.block(source_text, 'struct ' + name + r'\s*')
    assert unit in sequence_wrapper and unit in thread_wrapper
    structure_hashes[name] = hashlib.sha256(unit.encode()).hexdigest()
assert thread_wrapper == '#define THREADED 1\n' + sequence_wrapper.replace('#include "model-tests.h"', '#include "model-threaded-tests.h"')
for directory, report, count in [(sequential_dir, seq, 116), (threaded_dir, threads, 90)]:
    assert sha(directory / 'wrapper.c') == report['wrapper_sha256']
    assert len(report['results']) == 3
    assert {row['environment'] for row in report['results']} == {'host','sanitizers','aarch64'}
    for row in report['results']:
        env = row['environment']
        assert row['passed'] == count and row['failed'] == 0 and row['returncode'] == 0
        assert sha(directory / env) == row['binary_sha256']
        assert not (directory / (env + '-stderr.txt')).read_bytes()
        assert not (directory / (env + '-compile.txt')).read_bytes()
        output = (directory / (env + '-stdout.txt')).read_text()
        assert output.count('PASS ') == count and 'FAIL ' not in output
assert read(dt / 'verification-native-v1.json')['passed']
dt_report = read(dt / 'result.json')
assert dt_report['candidate_sha256'] == identities['dt_candidate'][1]
assert not dt_report['board_tested'] and not dt_report['new_battery_calibrated']
assert dt_report['properties'] == 16 and dt_report['only_battery_node_added']
properties = read(dt / 'original-properties.json')
fixture = (HERE / 'original-dt-fixture.h').read_text()
ocv = properties['decoded']['ocv_table']
assert len(ocv) == 21
assert 'static const u32 original_ocv[] = {' + ','.join(map(str,ocv)) + '};' in fixture
scalar_count = 0
for name, values in properties['decoded'].items():
    if name in ('compatible','ocv_table'):
        continue
    assert len(values) == 1
    assert int.from_bytes(bytes.fromhex(properties['properties_hex'][name]), 'big') == values[0]
    assert f'if (!strcmp(name,"{name}")) {{ *value={values[0]}; return 0; }}' in fixture
    scalar_count += 1
assert scalar_count == 14

OUT.mkdir(exist_ok=False)
records = {}

def copy(path, rel):
    target = OUT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists(), rel
    shutil.copyfile(path, target)
    value = sha(path)
    assert sha(target) == value
    records[Path(rel).as_posix()] = value

for name in ('original-v1', 'candidate-v1', 'candidate-v2', 'candidate-v3', 'candidate-v4'):
    for path in sorted((HERE / name).rglob('*')):
        if path.is_file():
            copy(path, path.relative_to(HERE))
for path in sorted(HERE.iterdir()):
    if path.is_file() and path.suffix in ('.py', '.h', '.md'):
        copy(path, path.name)
selected = ['green-v4','threaded-green-v4','red-v5','review-red-v1','debug-red-v2','threaded-pause-red-v2','plug-cache-red-v3','threaded-v3','kbuild-v5','dtb-v2']
for name in selected:
    for path in sorted((HERE / 'build' / name).iterdir()):
        if path.is_file():
            copy(path, path.relative_to(HERE))
for rel in kb['baseline_patches_sha256']:
    copy(ROOT / rel, Path('inputs') / rel)
for rel in ('outputs/rk3568-boot-package-20261005/dt-semantics-v2.py', 'outputs/rk3568-boot-package-20261005/libfdt-v2.py', 'outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb'):
    copy(ROOT / rel, Path('inputs') / rel)

manifest = {'format': 'sha256-evidence-bundle-v1', 'files_sha256': records,
            'excluded': ['build/kbuild-v5/kernel-source', 'build/kbuild-v5/kernel-build'],
            'excluded_reason': 'Full kernel checkout/O retained in original output; actual source, baseline patch hashes, config, compiler argv, object, .cmd, nm, ELF and logs are sealed.'}
manifest_path = OUT / 'manifest.json'
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
receipt = {
    'status': 'OFFLINE_LIFECYCLE_CANDIDATE_ONLY_WITH_ALGORITHM_ENABLEMENT_BLOCKER',
    'manifest_sha256': sha(manifest_path), 'files': len(records),
    'identities': {role: {'path': path.relative_to(HERE).as_posix(), 'sha256': value} for role, (path, value) in identities.items()},
    'kernel_commit': kb['kernel_commit'], 'compiler': kb['compiler'], 'kbuild_steps_exit0': 32,
    'exact_config_delta': delta, 'production_functions_sha256': units,
    'production_structs_sha256': structure_hashes,
    'model_counts_each_environment': {'sequential':116, 'pthread':90},
    'environments': ['host','ASan+UBSan','AArch64 static/QEMU'],
    'model_coverage': '32 byte-identical production functions and 2 structs; alloc/PS/IRQ/action failures, detached-todo devres, unique IRQ release, timer/monitor/resume/IRQ running callbacks joined against remove/shutdown/suspend; pause/probe plug cache races; finite input/read/calibration/RTC errors.',
    'model_dependencies': 'Current model-support/body/tests/threaded-tests/original-DT-fixture headers SHA-bound in manifest; APIs are userspace dependency models, not Linux scheduler or PMIC hardware. Current internal_calib starts with return; get_charge_status is stub0.',
    'red_evidence_scope': 'Previously executed historical binaries/wrappers/logs preserved; some dependency headers evolved after historical red runs, so current frozen headers are only bound as final green dependencies, not claimed as identical historical red build inputs.',
    'irq_owner': 'Non-devm request_threaded_irq/free_irq; partial request error frees first IRQ; later failure/remove/shutdown/last action use one serialized idempotent stop. No devm_free_irq during detached devres todo release.',
    'pause_semantics': 'Drain callbacks already admitted to protect lifecycle; paused IRQs may subsequently update plug-event cache. No atomic measurement snapshot claim.',
    'dt_semantics': 'Exactly original 16 battery properties added as one node to unchanged audio baseline; 3 identical real-libfdt products; pure-parser full metadata verification; DTC exit0 with 2699-byte warnings identical to SHA-bound preserved same-base same-DTC diagnostics.',
    'algorithm_enablement_blocker': {
        'missing_design_max_voltage': True,
        'candidate_parser_still_accepts_missing_value_as_0': True,
        'real_charge_status_may_finish_at_positive_current_below_500': True,
        'get_charge_status_stub0_not_covered_by_green_models': True,
        'integration_requirement': 'Reject unresolved battery DT before starting fuel-gauge algorithm. Resolve voltage/unit/Android/BQ compatibility from evidence; do not guess design voltage or calibration.'},
    'limitations': [
        'Original 3500mAh/3750qmax/21 OCV values/sample10mOhm/divider140:20 are original board config, not new battery calibration.',
        'Fuel-gauge writes GG/ADC/coulomb/SOC/calibration registers; not a read-only collector. Sticky I/O error does not roll back successful prior writes.',
        'Full ~3000-line fuel-gauge numeric algorithm, static SOC cache across devices and external power_supply pointer search not fully proved.',
        'No battery accuracy/load/charge/discharge tests; no real IRQ/MFD/PMIC error, suspend/resume/remove/shutdown hardware verification.',
        'No TSan/stress/full Image/modules run; actual Kbuild object only.',
        'Periodic calibration original early return retained; enabling dead calibration body requires fresh validation.'
    ],
    'accepted_for_board': False, 'image_built': False, 'board_tested': False,
    'new_battery_calibrated': False, 'charging_enabled': False,
    'public_patch_published': False, 'hardware_access': False,
}
receipt_path = OUT / 'receipt.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
for rel, expected in records.items():
    assert sha(OUT / rel) == expected, rel
result = {'receipt': str(receipt_path), 'receipt_sha256': sha(receipt_path),
          'manifest_sha256': sha(manifest_path), 'files': len(records), 'all_copies_sha_verified': True}
print(json.dumps(result))
