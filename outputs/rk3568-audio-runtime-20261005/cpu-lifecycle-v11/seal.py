#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Freeze actual model, Kbuild and replay evidence without modifying old outputs."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
from source_utils import function

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (HERE / 'receipt.json').exists() or (HERE / 'SHA256SUMS').exists():
        raise ValueError('New freeze already exists')
    inputs = json.loads((HERE / 'input-manifest.json').read_text())
    candidate = json.loads((HERE / 'source/manifest.json').read_text())
    prior = (HERE / 'inputs/outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10' / SOURCE).read_text()
    current = (HERE / 'source' / SOURCE).read_text()
    reduced = current
    for name in candidate['modified_functions']:
        new_body = function(current, name)
        old_body = function(prior, name)
        if reduced.count(new_body) != 1:
            raise ValueError('Expected exact changed production function')
        reduced = reduced.replace(new_body, old_body)
    if reduced != prior or candidate['modified_functions'] != ['rockchip_i2s_tdm_set_sysclk', 'i2s_checked_hw_params']:
        raise ValueError('Production changes escaped the two approved functions')
    legacy_marker = '\n\t/* Put set mclk rate into rockchip_i2s_tdm_set_mclk() */'
    if function(current, 'rockchip_i2s_tdm_set_sysclk').split(legacy_marker)[1] != function(prior, 'rockchip_i2s_tdm_set_sysclk').split(legacy_marker)[1]:
        raise ValueError('Legacy sysclk behavior changed')
    model_receipts = {}
    for directory, cases, red in [('shutdown-red-v10', 4, True), ('shutdown-green-v11', 48, False),
                                  ('params-regression-v11', 140, False)]:
        out = HERE / directory
        receipt = json.loads((out / 'result.json').read_text())
        expected_source = inputs['cpu_v10_sha256'] if red else candidate['source_sha256']
        if not receipt['model_only'] or receipt['board_tested'] or receipt['expected_red'] != red or receipt['source_sha256'] != expected_source or len(receipt['runs']) != 3:
            raise ValueError('Model scope/source mismatch')
        if sha(out / 'runner-snapshot.py') != receipt['test_sha256'] or \
                sha(out / 'test-sysclk-main.c') != receipt['main_sha256'] or \
                sha(out / 'simple-model-glue.h') != receipt['glue_sha256']:
            raise ValueError('Executed model source snapshots mismatch')
        for name, run in receipt['runs'].items():
            failures = ['simple_shutdown_clears_shared_requests'] if red else []
            if run['exit'] != (1 if red else 0) or run['tests'] != {'total': cases, 'passed': cases - int(red)} or run['failures'] != failures or \
                    sha(out / ('sysclk-' + name)) != run['binary_sha256'] or \
                    sha(out / (name + '.stdout')) != run['stdout_sha256'] or \
                    sha(out / (name + '.stderr')) != run['stderr_sha256']:
                raise ValueError('Actual model execution mismatch')
        model_receipts[directory] = sha(out / 'result.json')
    kbuild = json.loads((HERE / 'kbuild-object-v1/result.json').read_text())
    if kbuild['exit'] or kbuild['source_sha256'] != candidate['source_sha256'] or not kbuild['object_only'] or \
            kbuild['full_image_built'] or kbuild['board_tested'] or not kbuild['original_source_and_ABI_unchanged'] or \
            sha(HERE / 'kbuild-object-v1/objects/rockchip_i2s_tdm.o') != kbuild['object_sha256']:
        raise ValueError('Need exact actual full production object build')
    replay = HERE / 'patch-replay-v1'
    replay.mkdir(exist_ok=False)
    replay_receipts = {}
    for label, start, patch in [
            ('pristine', ROOT / 'third_party/linux-rk3588' / SOURCE, HERE / 'source/i2s-lifecycle-v11.patch'),
            ('v10', HERE / 'inputs/outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10' / SOURCE, HERE / 'source/delta-v10-v11.patch')]:
        tree = replay / label
        target = tree / SOURCE
        target.parent.mkdir(parents=True)
        shutil.copy2(start, target)
        result = subprocess.run(['patch', '--batch', '--forward', '-p1', '-d', str(tree), '-i', str(patch)], capture_output=True, text=True, timeout=30)
        (replay / (label + '.stdout')).write_text(result.stdout)
        (replay / (label + '.stderr')).write_text(result.stderr)
        if result.returncode or sha(target) != candidate['source_sha256']:
            raise ValueError('Actual patch replay differs from candidate')
        replay_receipts[label] = {'exit': result.returncode, 'patch_sha256': sha(patch), 'result_sha256': sha(target)}
    (replay / 'result.json').write_text(json.dumps(replay_receipts, indent=2) + '\n')
    for relative, digest in inputs['inputs_sha256'].items():
        if sha(HERE / 'inputs' / relative) != digest:
            raise ValueError('Frozen input copy changed')
    for relative, digest in inputs['protected_sha256'].items():
        if sha(ROOT / relative) != digest:
            raise ValueError('Protected old source/ABI/package changed')
    for relative, digest in kbuild['abi_inputs_sha256'].items():
        if sha(ROOT / '.deps/kernel/aiot-3568pq-audio-v1' / relative) != digest:
            raise ValueError('Actual old ABI metadata changed')
    receipt = {'version': 11, 'source_sha256': candidate['source_sha256'],
               'delta_patch_sha256': candidate['delta_patch_sha256'], 'patch_sha256': candidate['patch_sha256'],
               'object_sha256': kbuild['object_sha256'], 'object_bytes': kbuild['object_bytes'],
               'modified_functions': candidate['modified_functions'],
               'other_CPU_code_byte_exact': True, 'legacy_sysclk_branch_byte_exact': True,
               'input_manifest_sha256': sha(HERE / 'input-manifest.json'),
               'model_receipts_sha256': model_receipts, 'kbuild_result_sha256': sha(HERE / 'kbuild-object-v1/result.json'),
               'patch_replay_result_sha256': sha(replay / 'result.json'),
               'protected_old_inputs_verified': len(inputs['protected_sha256']),
               'old_actual_ABI_files_verified': len(kbuild['abi_inputs_sha256']),
               'board_tested': False, 'full_image_built': False, 'published': False,
               'audio_start_allowed': False, 'permits_reboot': False,
               'independent_review_completed': False,
               'scope': 'Offline actual function/caller models, exact whole production Kbuild object and patch replay; root alone integrates a future Image and does board comparison'}
    (HERE / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    files = {path.relative_to(HERE).as_posix(): sha(path) for path in sorted(HERE.rglob('*'))
             if path.is_file() and path.name not in ['SHA256SUMS', 'frozen-output-manifest.json']}
    (HERE / 'frozen-output-manifest.json').write_text(json.dumps({'board_tested': False, 'files_sha256': files}, indent=2) + '\n')
    files['frozen-output-manifest.json'] = sha(HERE / 'frozen-output-manifest.json')
    (HERE / 'SHA256SUMS').write_text(''.join(digest + '  ' + name + '\n' for name, digest in sorted(files.items())))
    print(json.dumps({'source_sha256': receipt['source_sha256'], 'object_sha256': receipt['object_sha256'],
                      'receipt_sha256': sha(HERE / 'receipt.json'), 'frozen_files': len(files),
                      'protected': receipt['protected_old_inputs_verified'], 'ABI_files': receipt['old_actual_ABI_files_verified']}))


if __name__ == '__main__':
    main()
