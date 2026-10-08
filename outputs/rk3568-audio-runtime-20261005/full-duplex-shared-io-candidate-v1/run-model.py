#!/usr/bin/env python3
"""Finite model runner; preserve every command, failed compile, and source identity."""
import argparse
import hashlib
import importlib.util
import json
import re
import stat
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARAMS = HERE.parent / 'full-duplex-params-candidate-v1'
spec = importlib.util.spec_from_file_location('source_utils', PARAMS / 'model-v4/source_utils.py')
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Nonordinary file ' + str(path))
    for parent in path.parents:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('Nonordinary ancestor')
        if parent == ROOT:
            return path
    raise ValueError('Outside root')


def check(model, manifest):
    current = {p.name: sha(ordinary(p).read_bytes()) for p in model.iterdir()
               if p.name != 'manifest.json'}
    if current != manifest['model_files_sha256']:
        raise ValueError('Model exact set/bytes drift')
    source = HERE / manifest['source']
    sources = {}
    for rel, expected in manifest['source_files'].items():
        data = ordinary(source / rel).read_bytes()
        if sha(data) != expected:
            raise ValueError('Bound finite source drift ' + rel)
        sources[rel] = data.decode()
    for rel, expected in manifest.get('external_source_files', {}).items():
        if not rel.startswith('@sdk/'):
            raise ValueError('Unknown external source ' + rel)
        path = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4' / rel[5:]
        data = ordinary(path).read_bytes()
        if sha(data) != expected:
            raise ValueError('External source drift ' + rel)
        sources[rel] = data.decode()
    for key, expected in manifest['actual_bodies_sha256'].items():
        rel, name = key.split(':')
        body = utils.function(sources[rel], name)
        if sha(body.encode()) != expected:
            raise ValueError('Bound production body drift ' + key)
        if not any(body in p.read_text() for p in model.iterdir() if p.suffix in ['.c', '.h']):
            raise ValueError('Production body absent from model ' + key)
    return {'source_files': manifest['source_files'], 'model_files': current}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--expect', choices=['red', 'green'], required=True)
    parser.add_argument('--expect-no-pm', choices=['red', 'green'], default='green')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'model-[a-z0-9-]+', args.model) or not re.fullmatch(r'[a-z0-9-]+', args.attempt):
        raise ValueError('Fresh local directory required')
    model = HERE / args.model
    data = ordinary(model / 'manifest.json').read_bytes()
    if sha(data) != args.manifest_sha256:
        raise ValueError('Reviewed manifest SHA differs')
    manifest = json.loads(data)
    before = check(model, manifest)
    if args.check:
        print(json.dumps({'status': 'FINITE_SOURCE_MODEL_PRECHECK',
                          'actual_functions': len(manifest['actual_bodies_sha256']),
                          'compiler_executed': False}))
        return 0
    out = HERE / ('runs-' + args.attempt)
    out.mkdir()
    (out / 'runner.py').write_bytes(Path(__file__).read_bytes())
    (out / 'manifest.json').write_bytes(data)
    receipt = {'scope': 'FINITE_SOURCE_PRIMITIVE_MODEL_NOT_KERNEL_OR_HARDWARE',
               'before': before, 'runs': {}, 'model_manifest_sha256': sha(data),
               'runner_sha256': sha(Path(__file__).read_bytes()),
               'Kbuild_executed': False, 'board_tested': False, 'START_authorized': False}

    def command(argv, name):
        result = subprocess.run(list(map(str, argv)), capture_output=True, timeout=45)
        (out / (name + '.stdout')).write_bytes(result.stdout)
        (out / (name + '.stderr')).write_bytes(result.stderr)
        record = {'argv': list(map(str, argv)), 'exit': result.returncode,
                  'stdout_bytes': len(result.stdout), 'stdout_sha256': sha(result.stdout),
                  'stderr_bytes': len(result.stderr), 'stderr_sha256': sha(result.stderr)}
        (out / (name + '.command.json')).write_text(json.dumps(record, indent=2) + '\n')
        return result, record

    unexpected = False
    full_outputs = []
    environments = [
        ('host', 'gcc', [], []),
        ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'], []),
        ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-static'], [ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static']),
    ]
    for label, compiler, flags, prefix in environments:
        binary = out / ('shared-io-' + label)
        result, record = command([compiler, '-std=gnu11', '-O0', '-Wall', '-Wextra', '-Werror',
                                  '-Wno-unused-parameter', '-Wno-unused-function', '-Wno-sign-compare',
                                  '-pthread', *flags, model / 'unit.c', '-o', binary], label + '-compile')
        run = {'compile': record}
        if result.returncode:
            unexpected = True
        else:
            result, record = command([*prefix, binary], label + '-execute')
            run['execution'] = record
            run['binary_sha256'] = sha(binary.read_bytes())
            full_outputs.append(result.stdout)
            rows = re.findall(r'^CHECK (\w+) ([01])$', result.stdout.decode(), re.M)
            summary = {'checks': len(rows), 'passed': sum(int(v) for _, v in rows),
                       'failed': sum(v == '0' for _, v in rows)}
            actual = json.loads(result.stdout.splitlines()[-1])
            run['observed'] = summary
            run['failed_labels'] = sorted({name for name, value in rows if value == '0'})
            valid = actual == summary and not result.stderr and result.returncode == (1 if args.expect == 'red' else 0)
            valid &= summary['failed'] > 0 if args.expect == 'red' else summary['failed'] == 0
            run['expected_scope_verified'] = bool(valid)
            unexpected |= not valid
        receipt['runs'][label] = run
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if (model / 'unit-no-pm-sleep.c').exists():
        binary = out / 'card-no-pm-sleep'
        result, record = command(['gcc', '-std=gnu11', '-O0', '-Wall', '-Wextra', '-Werror',
                                  '-Wno-unused-parameter', '-Wno-unused-function', '-Wno-sign-compare',
                                  '-pthread', model / 'unit-no-pm-sleep.c', '-o', binary], 'card-no-pm-sleep-compile')
        run = {'compile': record}
        unexpected |= result.returncode != 0
        if result.returncode == 0:
            result, record = command([binary], 'card-no-pm-sleep-execute')
            run['execution'] = record
            run['binary_sha256'] = sha(binary.read_bytes())
            expected = result.returncode == (1 if args.expect_no_pm == 'red' else 0) and not result.stderr
            run['expected_scope_verified'] = expected
            unexpected |= not expected
        receipt['no_pm_sleep_branch'] = run
    receipt['after'] = check(model, manifest)
    receipt['all_full_stdout_bytes_equal'] = len(full_outputs) == 3 and len(set(full_outputs)) == 1
    unexpected |= receipt['before'] != receipt['after'] or not receipt['all_full_stdout_bytes_equal']
    receipt['status'] = 'UNEXPECTED_FAILURE' if unexpected else 'EXPECTED_' + args.expect.upper()
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'],
                      'runs': {label: {'compile': run['compile']['exit'],
                                       'execution': run.get('execution', {}).get('exit'),
                                       'checks': run.get('observed')} for label, run in receipt['runs'].items()}}))
    return int(unexpected)


if __name__ == '__main__':
    raise SystemExit(main())
