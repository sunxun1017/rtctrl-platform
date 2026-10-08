#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only snapshot of the parent's fresh execution; this is not review approval."""
from pathlib import Path
import hashlib
import json
import shutil
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME = HERE.parent
SOURCE = RUNTIME / 'build/root-pcm-peer-idle-v1'
TOOL = RUNTIME / 'rerun-pcm-peer-idle-v1.py'
OUT = HERE / 'review-inputs-root-v1'
ROOT_RESULT_SHA = 'f300fd76c0e98311e970a71dd6debcee9929a87e993d357411d5be12bcb9115a'
ROOT_TOOL_SHA = 'dc4158b091f6dabcec3f846ce8e115cf32ed7296dd107db79cd6f87398e389c6'


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


def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def main():
    if OUT.exists():
        raise ValueError('Fresh owned evidence snapshot required')
    result_data = ordinary(SOURCE / 'result.json')
    tool_data = ordinary(TOOL)
    if digest(result_data) != ROOT_RESULT_SHA or digest(tool_data) != ROOT_TOOL_SHA:
        raise ValueError('Root evidence identity changed')
    result = json.loads(result_data)
    if result['root_fresh_compile_and_execution'] is not True or \
            result['actual_main_and_parameters_unchanged'] is not True or \
            result['invocation']['exit'] != 0 or result['board_tested'] is not False:
        raise ValueError('Unexpected root execution receipt')
    for name, expected in result['inputs_sha256'].items():
        if digest(ordinary(HERE / name)) != expected:
            raise ValueError('Current author input differs: ' + name)
    for name in ['pcm-peer-idle.c', 'parameters.h', 'model.c']:
        if ordinary(SOURCE / 'snapshot' / name) != ordinary(HERE / name):
            raise ValueError('Actual compiled root source differs: ' + name)
    runner = ordinary(HERE / 'run-models.py').decode()
    for old, new in [('ROOT = HERE.parents[2]', 'ROOT = HERE.parents[4]'),
                     ('RUNTIME = HERE.parent', 'RUNTIME = HERE.parents[2]')]:
        if runner.count(old) != 1:
            raise ValueError('Unexpected author runner layout')
        runner = runner.replace(old, new, 1)
    if ordinary(SOURCE / 'snapshot/run-models.py') != runner.encode():
        raise ValueError('Root runner differs beyond the two directory depths')
    actual = json.loads(ordinary(SOURCE / 'snapshot/runs-green/result.json'))
    if set(actual['results']) != {'host', 'asan-ubsan', 'aarch64-qemu'}:
        raise ValueError('Missing actual environment')
    for name, row in actual['results'].items():
        if row['passed'] != 1032 or row['total'] != 1032 or len(row['cases']) != 1032 or \
                not all(case['passed'] for case in row['cases']):
            raise ValueError('Incomplete root execution: ' + name)
        binary = SOURCE / 'snapshot/runs-green' / name / 'wrapped-peer'
        if digest(ordinary(binary)) != row['binary_sha256']:
            raise ValueError('Root executed binary changed: ' + name)
    entries = []
    for path in sorted(SOURCE.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        data = ordinary(path)
        relative = path.relative_to(SOURCE).as_posix()
        entries.append((path, Path('root-execution') / relative,
                        {'source': path.relative_to(ROOT).as_posix(), 'size': len(data),
                         'sha256': digest(data)}))
    entries.append((TOOL, Path('rerun-pcm-peer-idle-v1.py'),
                    {'source': TOOL.relative_to(ROOT).as_posix(), 'size': len(tool_data),
                     'sha256': digest(tool_data)}))
    OUT.mkdir()
    files = {}
    for source, relative, identity in entries:
        target = OUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
        if digest(ordinary(target)) != identity['sha256'] or \
                digest(ordinary(source)) != identity['sha256']:
            raise ValueError('Copy/source readback mismatch: ' + str(relative))
        files[relative.as_posix()] = identity
    receipt = {'files': files, 'ordinary_files': len(files),
               'root_result_sha256': ROOT_RESULT_SHA, 'root_runner_sha256': ROOT_TOOL_SHA,
               'actual_main_parameters_wrapper_unchanged': True,
               'copied_runner_changes_only_ROOT_and_RUNTIME_depth': True,
               'three_actual_environments': result['counts'],
               'source_readback_unchanged': True, 'root_review_completed': False,
               'independent_review_completed': False, 'frozen': False,
               'board_tested': False, 'START_authorized': False,
               'scope': 'Read-only byte snapshot of parent fresh model executions. Captured execution evidence is not review approval or hardware validation.',
               'timer_boundary': 'Default SIGALRM covers interruptible waits; uninterruptible kernel waits and stdout after alarm cancellation have no five-second guarantee.'}
    save(OUT / 'receipt.json', receipt)
    print(json.dumps({'files': len(files), 'receipt_sha256': digest(ordinary(OUT / 'receipt.json')),
                      'root_result_sha256': ROOT_RESULT_SHA, 'frozen': False}))


if __name__ == '__main__':
    main()
