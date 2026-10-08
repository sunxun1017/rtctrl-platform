#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run actual canonical_device/main with controlled syscalls, without host sysfs."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--red-v2', action='store_true')
    args = parser.parse_args()
    source = HERE.parent / 'session-guard-v2/audio-session-guard.c' if args.red_v2 else HERE / 'audio-session-guard.c'
    out = HERE / ('canonical-red-v2' if args.red_v2 else 'canonical-models')
    out.mkdir(exist_ok=False)
    evidence = []
    targets = [
        ('host', 'gcc', ['-O2'], []),
        ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer'], []),
        ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-O2', '-static'], [str(QEMU)]),
    ]
    for name, compiler, flags, prefix in targets:
        binary = out / ('canonical-' + name)
        argv = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-fno-ident',
                *flags, '-DGUARD_SOURCE="' + str(source) + '"',
                str(HERE / 'canonical-device-model.c'),
                '-Wl,--wrap=realpath', '-Wl,--wrap=statfs',
                '-Wl,--wrap=__realpath_chk',
                '-Wl,--wrap=getuid', '-Wl,--wrap=geteuid', '-o', str(binary)]
        compiled = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (out / (name + '-compile.stdout')).write_text(compiled.stdout)
        (out / (name + '-compile.stderr')).write_text(compiled.stderr)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)
        result = subprocess.run(prefix + [str(binary)], capture_output=True, text=True, timeout=60)
        (out / (name + '.stdout')).write_text(result.stdout)
        (out / (name + '.stderr')).write_text(result.stderr)
        rows = result.stdout.splitlines()
        actual = dict(row.split(' ') for row in rows)
        failures = [key for key, value in actual.items() if value != '1']
        expected_failures = ['production-fixed-dmac-identity', 'production-reject-old-dma-name'] if args.red_v2 else []
        valid = result.returncode == 0 and len(rows) == len(actual) == 13 and failures == expected_failures
        evidence.append({'target': name, 'cases': len(actual), 'passed': len(actual) - len(failures),
                         'failures': failures, 'exit': result.returncode,
                         'expected_red': args.red_v2, 'expected_red_reproduced': args.red_v2 and valid,
                         'compile_argv': argv, 'binary_sha256': sha(binary),
                         'stdout_sha256': sha(out / (name + '.stdout')),
                         'stderr_sha256': sha(out / (name + '.stderr'))})
        if not valid:
            (out / 'result.json').write_text(json.dumps({'model_only': True, 'board_tested': False,
                                                       'targets': evidence}, indent=2) + '\n')
            raise RuntimeError(f'{name}: unexpected model results {failures}; {result.stderr}')
    receipt = {'model_only': True, 'board_tested': False,
               'actual_production_source_sha256': sha(source),
               'model_source_sha256': sha(HERE / 'canonical-device-model.c'),
               'test_sha256': sha(Path(__file__)), 'expected_red': args.red_v2,
               'wrappers': ['realpath', '__realpath_chk', 'statfs', 'getuid', 'geteuid'],
               'real_sysfs_acceptance_tested': False, 'hardware_start_attempted': False,
               'runtime_stop_proof_tested': False,
               'scope': 'Actual production C canonical_device and main; model values at libc boundaries; driver identity intentionally fails before collection',
               'targets': evidence}
    (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'expected_red': args.red_v2, 'cases_per_target': 13,
                      'targets': [{k: row[k] for k in ('target', 'passed', 'failures')} for row in evidence]}))


if __name__ == '__main__':
    main()
