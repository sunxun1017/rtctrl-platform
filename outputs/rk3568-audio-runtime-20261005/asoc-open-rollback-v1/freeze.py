#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify existing evidence and freeze only the accepted private offline scope."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'outputs/rk3568-audio-runtime-20261005/full-duplex-contract-v1'
REMAINING = ['sequential_first_0_second_normal_START', 'sequential_first_1_second_normal_START',
             'concurrent_two_normal_START_commit_both', 'hypothetical_dual_joint_STOP_reaches_global_proof']


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check(ok, message):
    if not ok:
        raise ValueError(message)


def jsonread(p):
    return json.loads(p.read_text())


def snapshot_inputs():
    source = jsonread(HERE / 'source-manifest-v1.json')
    for name, item in source['inputs'].items():
        check(sha(ROOT / name) == sha(HERE / item['snapshot']) == item['sha256'], 'Source/snapshot ' + name)
    for name, item in source['files'].items():
        check(sha(HERE / 'source-v1' / name) == item['sha256'], 'Candidate ' + name)
    check(sha(HERE / 'candidate-v1.patch') == source['patch_sha256'], 'Patch SHA')
    root = jsonread(HERE / 'review-evidence-v1/input-manifest.json')
    for name, item in root['inputs'].items():
        check(sha(ROOT / name) == sha(HERE / item['snapshot']) == item['sha256'], 'Root review/snapshot ' + name)
    final_review = jsonread(HERE / 'review-evidence-v1/root-final-review-input.json')
    check(sha(ROOT / final_review['source']) == sha(HERE / final_review['snapshot']) ==
          final_review['sha256'], 'Final root review source/snapshot')
    check(root['root_inputs_unchanged'] and root['all_six_fresh_compiles_and_runs_match'], 'Root acceptance')
    return source, root


def verify_model(mode, source):
    model = HERE / ('model-' + mode + '-v2')
    runs = HERE / ('runs-' + ('green' if mode == 'green' else 'red') + 'v1')
    manifest = jsonread(model / 'input-manifest.json')
    receipt = jsonread(runs / 'receipt.json')
    count = 70 if mode == 'green' else 68
    wanted = {'contract_total': 25, 'contract_passed': 21 if mode == 'green' else 0,
              'boundary_total': 110, 'boundary_passed': 110}
    check(receipt['fixed_counts'] == wanted and len(manifest['production_functions_sha256']) == count, 'Fixed counts')
    check(sha(model / 'input-manifest.json') == receipt['input_manifest_sha256'] and
          manifest['production_functions_sha256'] == receipt['production_functions_sha256'], 'Model manifest')
    check(sha(model / 'unit.c') == manifest['unit_sha256'], 'Unit SHA')
    check(sha(runs / 'runner-snapshot.py') == sha(HERE / 'run-model.py') == receipt['runner_sha256'], 'Runner SHA')
    for name, digest in receipt['model_files_sha256'].items():
        check(sha(model / name) == digest, 'Model file ' + name)
    for name, item in manifest['source_files'].items():
        check(sha(HERE / item['source']) == item['sha256'] == source['files'][name][
              'sha256' if mode == 'green' else 'original_sha256'], 'Model full source')
    spec = importlib.util.spec_from_file_location('sealed_source_utils', model / 'source_utils.py')
    util = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(util)
    for key, digest in manifest['production_functions_sha256'].items():
        group, name = key.split(':')
        group_text = (model / ('actual-' + group + '-functions.c')).read_text()
        if group == 'component-header':
            start = group_text.index('static inline unsigned int\nsnd_soc_component_active(')
            body = group_text[start:group_text.index('\n}', start) + 2]
        else:
            body = util.function(group_text, name)
        check(hashlib.sha256(body.encode()).hexdigest() == digest and body in (model / 'unit.c').read_text(),
              'Actual function ' + key)
    for label, record in receipt['runs'].items():
        check(record['compile']['exit'] == 0 and record['execution']['exit'] == 1 and
              record['expected_scope_verified'] and record['counts'] == record['line_counts'] == wanted,
              'Compile/execution ' + label)
        for stem, field in [(label + '-compile', 'compile'), (label, 'execution')]:
            for ext in ['stdout', 'stderr']:
                check(sha(runs / (stem + '.' + ext)) == record[field][ext + '_sha256'], 'Log SHA')
        check(not (runs / (label + '.stderr')).read_bytes() and
              not (runs / (label + '-compile.stderr')).read_bytes(), 'Nonempty stderr')
        text = (runs / (label + '.stdout')).read_text().splitlines()
        contract = [line.split() for line in text if line.startswith('CONTRACT_CHECK ')]
        boundary = [line.split() for line in text if line.startswith('BOUNDARY_CHECK ')]
        actual = {'contract_total': len(contract), 'contract_passed': sum(int(x[2]) for x in contract),
                  'boundary_total': len(boundary), 'boundary_passed': sum(int(x[2]) for x in boundary)}
        check(actual == json.loads(text[-1]) == wanted and len({x[1] for x in boundary}) == 74, 'Raw row counts')
        check(sha(runs / ('caller-chain-' + label)) == record['binary_sha256'], 'Binary SHA')
        if mode == 'green':
            check([x[1] for x in contract if x[2] == '0'] == REMAINING, 'Remaining red list')
    return {'functions': count, 'fixed_counts': wanted, 'boundary_unique_labels': 74,
            'manifest_sha256': sha(model / 'input-manifest.json'), 'receipt_sha256': sha(runs / 'receipt.json')}


def verify_kbuild(source):
    path = HERE / 'kbuild-v2'
    receipt = jsonread(path / 'receipt.json')
    check(receipt['accepted_offline_object_check'] and receipt['original_inputs_and_ABI_unchanged'], 'Kbuild accepted')
    for group, subdir in [('current_config_result', 'current-config'), ('compressed_branch_result', 'compressed-branch')]:
        for step in receipt[group]['steps']:
            check(step['exit'] == 0, 'Kbuild step exit')
            for ext in ['stdout', 'stderr']:
                check(sha(path / subdir / (step['label'] + '.' + ext)) == step[ext + '_sha256'], 'Kbuild log SHA')
        for name, item in receipt[group]['objects'].items():
            objects = path / subdir / 'objects'
            check(sha(objects / Path(name).name) == item['source_sha256'] == source['files'][name]['sha256'], 'Built source')
            check(sha(objects / (Path(name).stem + '.o')) == item['object_sha256'], 'Built object')
            command = objects / ('.' + Path(name).stem + '.o.cmd')
            check(sha(command) == item['command_sha256'] and '-DMODULE' not in command.read_text().splitlines()[0], 'Built-in command')
        check(sha(path / subdir / 'objects/built-in.a') == receipt[group]['built_in_archive_sha256'], 'Archive SHA')
    check(not receipt['compressed_branch_Kconfig_generated'] and not receipt['compressed_branch_ABI_validated']
          and not receipt['board_config_compressed_enabled'], 'Compressed scope')
    return sha(path / 'receipt.json')


def replay_patch(preflight, source):
    replay = preflight / 'replay'
    replay.mkdir()
    for name in source['files']:
        p = replay / name
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / 'inputs-v1' / Path(name).name, p)
    argv = ['patch', '-p1', '--fuzz=0', '--batch', '--input', str(HERE / 'candidate-v1.patch')]
    p = subprocess.run(argv, cwd=replay, capture_output=True, text=True)
    (preflight / 'patch.stdout').write_text(p.stdout)
    (preflight / 'patch.stderr').write_text(p.stderr)
    check(p.returncode == 0 and not p.stderr, 'Patch replay failed')
    for name, item in source['files'].items():
        check(sha(replay / name) == item['sha256'], 'Patch replay output')
    (preflight / 'patch-result.json').write_text(json.dumps({'argv': argv, 'exit': p.returncode,
              'strict_no_fuzz_replay_matches_four_sources': True}, indent=2) + '\n')


def external_inventory(preflight, source, root):
    regular = {name: item['sha256'] for name, item in source['inputs'].items()}
    regular.update({name: item['sha256'] for name, item in root['inputs'].items()})
    final_review = jsonread(HERE / 'review-evidence-v1/root-final-review-input.json')
    regular[final_review['source']] = final_review['sha256']
    kbuild = jsonread(HERE / 'kbuild-v2/receipt.json')
    regular.update(kbuild['protected_sha256'])
    for name, digest in kbuild['abi_inputs_sha256'].items():
        regular['.deps/kernel/aiot-3568pq-audio-v3/' + name] = digest
    links = {}
    kernel = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v3'
    for name, item in kbuild['kernel_inputs_sha256'].items():
        key = '.deps/kernel-source/aiot-3568pq-audio-v3/' + name
        if isinstance(item, str):
            regular[key] = item
        else:
            links[key] = item
    for name, digest in regular.items():
        p = ROOT / name
        check(p.is_file() and not p.is_symlink() and sha(p) == digest, 'External regular input ' + name)
    for name, item in links.items():
        p = ROOT / name
        check(p.is_symlink() and str(p.readlink()) == item['link_target'] and
              p.resolve().is_relative_to(kernel.resolve()) and
              p.resolve().relative_to(kernel.resolve()).as_posix() == item['resolved_relative'] and
              sha(p) == item['resolved_sha256'], 'Explicit SDK-internal link ' + name)
    record = {'regular_files_sha256': regular, 'regular_file_count': len(regular),
              'SDK_internal_links': links, 'SDK_internal_link_count': len(links),
              'links_not_counted_as_regular_files': True, 'all_current_inputs_sha_equal': True}
    (preflight / 'external-inputs.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    review = jsonread(HERE / 'review-acceptance-v1.json')
    check(review['root_authorized_freeze'] and review['independent_readonly_acceptance'] and
          review['scope'] == 'offline_private_ASoC_open_close_PM_candidate', 'Review acceptance required')
    source, root = snapshot_inputs()
    red = verify_model('red', source)
    green = verify_model('green', source)
    kbuild_sha = verify_kbuild(source)
    root_result = jsonread(HERE / 'review-evidence-v1/root-asoc-candidate-v2/result.json')
    check(root_result['all_six_fresh_compiles_and_runs_match'] and not root_result['board_tested'], 'Root fresh limited scope')
    preflight = HERE / 'freeze-preflight-v1'
    preflight.mkdir(exist_ok=False)
    replay_patch(preflight, source)
    external = external_inventory(preflight, source, root)
    files = {}
    for p in sorted(HERE.rglob('*')):
        if p.is_symlink():
            raise ValueError('Owned symlink: ' + str(p))
        if p.is_file() and '__pycache__' not in p.parts:
            files[p.relative_to(HERE).as_posix()] = sha(p)
    out = HERE / 'sealed-v1'
    out.mkdir(exist_ok=False)
    manifest = {'schema': 'asoc-open-rollback-offline-files-v1', 'files_sha256': files,
                'regular_file_count': len(files), 'scope': review['scope'],
                'includes_old_failures_and_root_snapshots': True}
    (out / 'file-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    sums = ''.join(digest + '  ' + name + '\n' for name, digest in files.items())
    sums += sha(out / 'file-manifest.json') + '  sealed-v1/file-manifest.json\n'
    (out / 'SHA256SUMS').write_text(sums)
    receipt = {'schema': 'asoc-open-rollback-offline-seal-v1', 'scope': review['scope'],
               'file_manifest_sha256': sha(out / 'file-manifest.json'), 'regular_file_count': len(files),
               'SHA256SUMS_sha256': sha(out / 'SHA256SUMS'),
               'external_inputs_manifest_sha256': sha(preflight / 'external-inputs.json'),
               'external_regular_file_count': external['regular_file_count'],
               'external_SDK_internal_link_count': external['SDK_internal_link_count'],
               'source_manifest_sha256': sha(HERE / 'source-manifest-v1.json'),
               'source_sha256': {name: v['sha256'] for name, v in source['files'].items()},
               'patch_sha256': source['patch_sha256'], 'red': red, 'green': green,
               'kbuild_receipt_sha256': kbuild_sha, 'root_review_snapshot_manifest_sha256': sha(HERE / 'review-evidence-v1/input-manifest.json'),
               'root_runner_sha256': root['root_runner_sha256'], 'root_result_sha256': root['root_result_sha256'],
               'review_acceptance_sha256': sha(HERE / 'review-acceptance-v1.json'),
               'remaining_business_reds': REMAINING, 'CPU_v12_modified': False,
               'full_image_built': False, 'board_tested': False, 'accepted_for_board': False,
               'full_duplex_passed': False, 'duplex_START_authorized': False,
               'compressed_branch_Kconfig_generated': False, 'compressed_branch_ABI_validated': False,
               'limitations': ['API model is not complete kernel/hardware proof', '110 observations, 74 unique labels',
                    'compressed manual two-flag source branch only; board config disabled',
                    'RK817 voice shared cache and general pinctrl pending PM owner not closed',
                    'dual START/peer-preserving STOP/shared fault/TRCM/DMA isolation not closed']}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    for name, digest in files.items():
        check(sha(HERE / name) == digest, 'Freeze final inventory changed: ' + name)
    check(sha(out / 'file-manifest.json') == receipt['file_manifest_sha256'], 'Freeze manifest')
    for line in (out / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        check(sha(HERE / name) == digest, 'SHA256SUMS readback')
    check(sha(out / 'SHA256SUMS') == receipt['SHA256SUMS_sha256'], 'SHA256SUMS SHA')
    print(json.dumps({'files': len(files), 'receipt_sha256': sha(out / 'receipt.json'),
                      'manifest_sha256': receipt['file_manifest_sha256'],
                      'SUM_sha256': receipt['SHA256SUMS_sha256'], 'accepted_for_board': False}))


if __name__ == '__main__':
    main()
