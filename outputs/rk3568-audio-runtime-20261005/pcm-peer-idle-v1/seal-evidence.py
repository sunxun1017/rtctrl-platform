#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Archive the exact reviewed helper and all executed evidence, without board access."""
from pathlib import Path
import hashlib
import json
import shutil
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'sealed-evidence-v1'
NOTE = HERE.parent / 'REVIEW-PCM-PEER-IDLE-20261006.md'
NOTE_SHA = '569f6ed7e09e58c82eb9a9388fddb8f928d8b9df855d86fdf20e4b10ef02b69d'
READY_SHA = 'a0e7808ab39ab9b220594aaa41690d818f05e25261d4d288ea8725a785588e2a'
ROOT_RESULT_SHA = 'f300fd76c0e98311e970a71dd6debcee9929a87e993d357411d5be12bcb9115a'
ROOT_COPY_SHA = 'af60d6e8d2fa9a615142fd0c897e18bee5597dd6dc6cff5e9ac823f249047302'
PRODUCTION_SHA = '30e074fd01cbe94bc8e28a20de19698c5492525af469615afc7daaac92331779'


def ordinary(path):
    if not path.is_relative_to(ROOT) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Ordinary repository file required: ' + str(path))
    ancestor = path.parent
    while True:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError('Nonordinary ancestor: ' + str(ancestor))
        if ancestor == ROOT:
            break
        ancestor = ancestor.parent
    return path.read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return digest(ordinary(path))


def load(path, expected=None):
    data = ordinary(path)
    if expected is not None and digest(data) != expected:
        raise ValueError('Fixed evidence identity changed: ' + str(path))
    return json.loads(data)


def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def check_external(records):
    for relative, expected in records.items():
        if sha(ROOT / relative) != expected:
            raise ValueError('Protected original changed: ' + relative)


def main():
    if OUT.exists() or (HERE / 'review-acceptance-v1').exists():
        raise ValueError('Fresh owned seal and acceptance snapshot required')
    note_data = ordinary(NOTE)
    if digest(note_data) != NOTE_SHA:
        raise ValueError('Root acceptance identity changed')
    ready = load(HERE / 'ready-for-review-v1.json', READY_SHA)
    for relative, expected in ready['files_sha256'].items():
        if sha(HERE / relative) != expected:
            raise ValueError('Reviewed author candidate changed: ' + relative)
    inputs = load(HERE / 'input-manifest.json')
    check_external(inputs['external_inputs_sha256'])
    for relative, expected in inputs['external_inputs_sha256'].items():
        if sha(HERE / 'inputs' / relative) != expected:
            raise ValueError('Protected input snapshot changed: ' + relative)
    copied_root = load(HERE / 'review-inputs-root-v1/receipt.json', ROOT_COPY_SHA)
    for relative, identity in copied_root['files'].items():
        target = HERE / 'review-inputs-root-v1' / relative
        if sha(target) != identity['sha256'] or len(ordinary(target)) != identity['size'] or \
                sha(ROOT / identity['source']) != identity['sha256']:
            raise ValueError('Root evidence snapshot/source mismatch: ' + relative)
    root_run = load(HERE / 'review-inputs-root-v1/root-execution/result.json', ROOT_RESULT_SHA)
    if root_run['root_fresh_compile_and_execution'] is not True or \
            root_run['actual_main_and_parameters_unchanged'] is not True:
        raise ValueError('Root actual execution not verified')
    for name, row in root_run['counts'].items():
        if row != {'passed': 1032, 'total': 1032}:
            raise ValueError('Root execution incomplete: ' + name)
    production = load(HERE / 'production-v2/manifest.json', PRODUCTION_SHA)
    model = load(HERE / 'models-green-v1/result.json', production['model_result_sha256'])
    for name, row in model['results'].items():
        if row['passed'] != 1032 or row['total'] != 1032 or len(row['cases']) != 1032 or \
                not all(case['passed'] for case in row['cases']) or \
                sha(HERE / 'models-green-v1' / name / 'wrapped-peer') != row['binary_sha256']:
            raise ValueError('Author executed evidence mismatch: ' + name)
    for relative, expected in [('pcm-peer-idle.c', production['source_sha256']),
                               ('parameters.h', production['parameters_header_sha256']),
                               ('production-v2/pcm-peer-idle', production['binary_sha256'])]:
        if sha(HERE / relative) != expected:
            raise ValueError('Reviewed production identity changed: ' + relative)
    acceptance = HERE / 'review-acceptance-v1'
    acceptance.mkdir()
    (acceptance / 'root-acceptance.md').write_bytes(note_data)
    save(acceptance / 'receipt.json',
         {'source': NOTE.relative_to(ROOT).as_posix(), 'sha256': NOTE_SHA,
          'size': len(note_data), 'root_review_completed': True,
          'independent_review_completed': True, 'authority': 'Copied root acceptance note explicitly records the root fresh execution and independent read-only acceptance.',
          'board_tested': False, 'START_authorized': False})
    entries = []
    for path in sorted(HERE.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        data = ordinary(path)
        entries.append((path, path.relative_to(HERE), len(data), digest(data)))
    OUT.mkdir()
    files = {}
    for source, relative, size, expected in entries:
        target = OUT / 'source-inputs' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
        if sha(target) != expected or sha(source) != expected:
            raise ValueError('Archive/source readback mismatch: ' + relative.as_posix())
        files[target.relative_to(OUT).as_posix()] = {
            'source': source.relative_to(ROOT).as_posix(), 'size': size,
            'sha256': expected}
    external = dict(inputs['external_inputs_sha256'])
    external[NOTE.relative_to(ROOT).as_posix()] = NOTE_SHA
    for identity in copied_root['files'].values():
        external[identity['source']] = identity['sha256']
    check_external(external)
    save(OUT / 'inventory.json',
         {'files': files, 'ordinary_archive_files': len(files),
          'all_copies_readback_equal': True, 'external_inputs_readback_sha256': external,
          'external_files_unchanged': True, 'reviewed_initial_candidate_files': len(ready['files_sha256']),
          'source_tree_excludes_only_the_new_seal_directory': True})
    receipt = {
        'frozen': True, 'freeze_kind': 'Fresh ordinary byte archive with full SHA-256 inventory and checksum list; old records retained as generated.',
        'freeze_scope': 'All helper inputs, sources/tools, author red/green actual executions, failed history, static production ELF, full copied root fresh execution and acceptance note.',
        'inventory_sha256': sha(OUT / 'inventory.json'), 'ordinary_archive_files': len(files),
        'reviewed_initial_candidate_inventory_sha256': READY_SHA,
        'root_review_completed': True, 'independent_review_completed': True,
        'root_acceptance_sha256': NOTE_SHA, 'root_result_sha256': ROOT_RESULT_SHA,
        'root_full_execution_snapshot_receipt_sha256': ROOT_COPY_SHA,
        'source_sha256': production['source_sha256'],
        'parameters_header_sha256': production['parameters_header_sha256'],
        'production_manifest_sha256': PRODUCTION_SHA,
        'binary_sha256': production['binary_sha256'], 'binary_bytes': production['binary_bytes'],
        'binary_crc32': production['binary_crc32'], 'static_AArch64_ELF': True,
        'author_model_result_sha256': production['model_result_sha256'],
        'author_actual_environments': production['model_environments'],
        'root_actual_environments': root_run['counts'],
        'old_inputs_unchanged': True, 'external_readback_files': len(external),
        'board_tested': False, 'PREPARE_or_START_permission': False, 'frames_transferred': 0,
        'kernel_PM_DMA_or_shared_sysclk_proven': False,
        'timer_boundary': 'Five-second SIGALRM actual execution covers interruptible pause only. Uninterruptible kernel waits and stdout after alarm cancellation have no five-second guarantee.',
        'hardware_scope': 'Offline only. Fully-closed pre/post guard; real four-order board matrix requires separately reviewed candidate Image/codec/package and parent-owned board execution.'}
    save(OUT / 'receipt.json', receipt)
    checksum_entries = {relative: identity['sha256'] for relative, identity in files.items()}
    checksum_entries['inventory.json'] = sha(OUT / 'inventory.json')
    checksum_entries['receipt.json'] = sha(OUT / 'receipt.json')
    with (OUT / 'SHA256SUMS').open('x') as handle:
        for relative, expected in sorted(checksum_entries.items()):
            handle.write(expected + '  ' + relative + '\n')
    for relative, expected in checksum_entries.items():
        if sha(OUT / relative) != expected:
            raise ValueError('Final archive checksum mismatch: ' + relative)
    check_external(external)
    print(json.dumps({'receipt_sha256': sha(OUT / 'receipt.json'),
                      'inventory_sha256': sha(OUT / 'inventory.json'),
                      'SHA256SUMS_sha256': sha(OUT / 'SHA256SUMS'),
                      'archive_files': len(files), 'checksum_entries': len(checksum_entries),
                      'external_readback_files': len(external),
                      'binary_sha256': production['binary_sha256'], 'frozen': True}))


if __name__ == '__main__':
    main()
