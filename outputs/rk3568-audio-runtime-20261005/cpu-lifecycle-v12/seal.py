#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify and freeze actual model/object/replay evidence; no old writes."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
from source_utils import function

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = HERE.parent / 'cpu-lifecycle-v11'
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (HERE / 'receipt.json').exists() or (HERE / 'SHA256SUMS').exists():
        raise ValueError('Freeze already exists')
    inputs = json.loads((HERE / 'input-manifest.json').read_text())
    candidate = json.loads((HERE / 'source/manifest.json').read_text())
    prior_path = HERE / 'inputs/outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v11/source' / SOURCE
    prior = prior_path.read_text()
    current = (HERE / 'source' / SOURCE).read_text()
    if sha(HERE / 'source' / SOURCE) != candidate['source_sha256']:
        raise ValueError('Candidate identity')
    expected_functions = ['i2s_checked_runtime_suspend', 'i2s_checked_set_fmt']
    reduced = current
    for name in expected_functions:
        body = function(current, name)
        if reduced.count(body) != 1:
            raise ValueError('Unexpected function occurrences')
        reduced = reduced.replace(body, function(prior, name))
    if reduced.count('\tbool format_pm_release;\n') != 1:
        raise ValueError('Expected one new private field')
    reduced = reduced.replace('\tbool format_pm_release;\n', '')
    if reduced != prior or candidate['modified_functions'] != expected_functions:
        raise ValueError('Source changes escaped the approved field/two functions')
    # Every hardware operation in suspend, the public sysfs formatter, gates,
    # START/startup/teardown and v11 cache-reset/params remain exact.
    for name in ['i2s_checked_gate_locked', 'i2s_checked_quiesce',
                 'i2s_checked_probe_clock_release', 'i2s_checked_component_trigger',
                 'rockchip_i2s_tdm_startup', 'rockchip_i2s_tdm_set_sysclk',
                 'i2s_checked_hw_params']:
        if function(current, name) != function(prior, name):
            raise ValueError('Unapproved gate/cleanup/v11 behavior changed')
    models = {}
    for directory, cases, red in [('format-pm-red-v11-r2', 5, True),
                                  ('format-pm-green-v12-r4', 90, False),
                                  ('shutdown-green-v12', 48, False),
                                  ('params-regression-v12', 140, False)]:
        out = HERE / directory
        result = json.loads((out / 'result.json').read_text())
        expected_source = inputs['cpu_v11_sha256'] if red else candidate['source_sha256']
        if not result['model_only'] or result['board_tested'] or result['expected_red'] != red or result['source_sha256'] != expected_source or len(result['runs']) != 3:
            raise ValueError('Model identity/scope mismatch')
        fmt = directory.startswith('format-pm-')
        runner_key = 'runner_sha256' if fmt else 'test_sha256'
        main_name = 'test-format-pm-main.c' if fmt else 'test-sysclk-main.c'
        if sha(out / 'runner-snapshot.py') != result[runner_key] or sha(out / main_name) != result['main_sha256']:
            raise ValueError('Executed runner/main snapshot mismatch')
        if not fmt and sha(out / 'simple-model-glue.h') != result['glue_sha256']:
            raise ValueError('Regression glue mismatch')
        for name, run in result['runs'].items():
            failures = ['worker_before_fmt_out_reaches_idle'] if red else []
            binary = out / (('format-pm-' if fmt else 'sysclk-') + name)
            if run['exit'] != int(red) or run['tests'] != {'total': cases, 'passed': cases - int(red)} or run['failures'] != failures or \
                    sha(binary) != run['binary_sha256'] or sha(out / (name + '.stdout')) != run['stdout_sha256'] or sha(out / (name + '.stderr')) != run['stderr_sha256']:
                raise ValueError('Actual model execution readback mismatch')
        if fmt:
            actual = (out / 'actual-functions.c').read_text()
            for name, digest in result['production_functions_sha256'].items():
                if hashlib.sha256(function(actual, name).encode()).hexdigest() != digest or function(actual, name) != function(prior if red else current, name):
                    raise ValueError('Model production extraction changed')
        models[directory] = sha(out / 'result.json')
    kbuild = json.loads((HERE / 'kbuild-object-v2/result.json').read_text())
    if kbuild['exit'] or kbuild['source_sha256'] != candidate['source_sha256'] or not kbuild['object_only'] or \
            kbuild['full_image_built'] or kbuild['board_tested'] or not kbuild['original_source_and_ABI_unchanged'] or \
            sha(HERE / 'kbuild-object-v2/objects/rockchip_i2s_tdm.o') != kbuild['object_sha256']:
        raise ValueError('Need full production AArch64 Kbuild object')
    replay = HERE / 'patch-replay-v1'
    replay.mkdir(exist_ok=False)
    replay_results = {}
    for label, source, patch in [('pristine', ROOT / 'third_party/linux-rk3588' / SOURCE, HERE / 'source/i2s-lifecycle-v12.patch'),
                                  ('v11', prior_path, HERE / 'source/delta-v11-v12.patch')]:
        tree = replay / label
        target = tree / SOURCE
        target.parent.mkdir(parents=True)
        shutil.copy2(source, target)
        argv = ['patch', '--batch', '--forward', '-p1', '-d', str(tree), '-i', str(patch)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        (replay / (label + '.stdout')).write_text(result.stdout)
        (replay / (label + '.stderr')).write_text(result.stderr)
        if result.returncode or sha(target) != candidate['source_sha256']:
            raise ValueError('Actual production patch replay differs')
        replay_results[label] = {'argv': argv, 'exit': result.returncode,
                                  'patch_sha256': sha(patch), 'result_sha256': sha(target)}
    (replay / 'result.json').write_text(json.dumps(replay_results, indent=2) + '\n')
    for name, digest in inputs['inputs_sha256'].items():
        if sha(HERE / 'inputs' / name) != digest:
            raise ValueError('Input snapshot changed')
    for name, digest in inputs['protected_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('Actual old source/Image/ABI/package changed')
    for name, digest in inputs['v11_files_sha256'].items():
        if sha(PRIOR / name) != digest:
            raise ValueError('Prior v11 frozen file changed')
    for name, digest in [('frozen-output-manifest.json', inputs['v11_inventory_sha256']),
                         ('SHA256SUMS', inputs['v11_SHA256SUMS_sha256'])]:
        if sha(PRIOR / name) != digest:
            raise ValueError('Prior v11 inventory/SUM changed')
    for name, digest in kbuild['abi_inputs_sha256'].items():
        if sha(ROOT / '.deps/kernel/aiot-3568pq-audio-v2' / name) != digest:
            raise ValueError('Actual integrated ABI changed')
    receipt = {'version': 12, 'source_sha256': candidate['source_sha256'],
               'delta_patch_sha256': candidate['delta_patch_sha256'], 'patch_sha256': candidate['patch_sha256'],
               'object_sha256': kbuild['object_sha256'], 'object_bytes': kbuild['object_bytes'],
               'modified_functions': expected_functions, 'added_private_field': 'bool format_pm_release',
               'other_CPU_code_byte_exact': True, 'strict_guard_sysfs_format_unchanged': True,
               'v11_zero_and_hw_params_byte_exact': True,
               'input_manifest_sha256': sha(HERE / 'input-manifest.json'),
               'model_receipts_sha256': models, 'kbuild_result_sha256': sha(HERE / 'kbuild-object-v2/result.json'),
               'patch_replay_result_sha256': sha(replay / 'result.json'),
               'prior_v11_files_verified': len(inputs['v11_files_sha256']),
               'actual_ABI_files_verified': len(kbuild['abi_inputs_sha256']),
               'protected_inputs_verified': len(inputs['protected_sha256']),
               'board_tested': False, 'full_image_built': False, 'published': False,
               'audio_start_allowed': False, 'independent_review_completed': False,
               'scope': 'Offline production-function API interleavings, whole production Kbuild object and patch replay; root owns new Image and natural initial-idle board comparison.'}
    (HERE / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    files = {}
    for path in sorted(HERE.rglob('*')):
        if path.is_symlink():
            raise ValueError('Cannot freeze symlink')
        relative = path.relative_to(HERE).as_posix()
        if path.is_file() and relative not in ['frozen-output-manifest.json', 'SHA256SUMS']:
            files[relative] = sha(path)
    (HERE / 'frozen-output-manifest.json').write_text(json.dumps({'board_tested': False, 'files_sha256': files}, indent=2) + '\n')
    files['frozen-output-manifest.json'] = sha(HERE / 'frozen-output-manifest.json')
    (HERE / 'SHA256SUMS').write_text(''.join(digest + '  ' + name + '\n' for name, digest in sorted(files.items())))
    print(json.dumps({'source_sha256': receipt['source_sha256'], 'object_sha256': receipt['object_sha256'],
                      'receipt_sha256': sha(HERE / 'receipt.json'),
                      'inventory_sha256': sha(HERE / 'frozen-output-manifest.json'),
                      'SHA256SUMS_sha256': sha(HERE / 'SHA256SUMS'), 'frozen_files': len(files)}))


if __name__ == '__main__':
    main()
