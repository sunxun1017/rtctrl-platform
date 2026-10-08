#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Actual production stage routing/collector, with cache syscall fixtures."""
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
    parser.add_argument('--red-v3', action='store_true')
    args = parser.parse_args()
    source = HERE.parent / 'session-guard-v3/audio-session-guard.c' if args.red_v3 else HERE / 'audio-session-guard.c'
    out = HERE / ('clock-stage-red-v3' if args.red_v3 else 'clock-stage-models')
    out.mkdir(exist_ok=False)
    evidence = []
    targets = [
        ('host', 'gcc', ['-O2'], []),
        ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer'], []),
        ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-O2', '-static'], [str(QEMU)]),
    ]
    for name, compiler, flags, prefix in targets:
        binary = out / ('clock-stage-' + name)
        argv = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-fno-ident',
                *flags, '-DGUARD_SOURCE="' + str(source) + '"', str(HERE / 'clock-stage-model.c'),
                '-Wl,--wrap=realpath', '-Wl,--wrap=__realpath_chk', '-Wl,--wrap=statfs',
                '-Wl,--wrap=getuid', '-Wl,--wrap=geteuid', '-Wl,--wrap=lstat',
                '-Wl,--wrap=open', '-Wl,--wrap=__open_2', '-Wl,--wrap=read', '-Wl,--wrap=close',
                '-Wl,--wrap=__read_chk',
                '-o', str(binary)]
        compiled = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (out / (name + '-compile.stdout')).write_text(compiled.stdout)
        (out / (name + '-compile.stderr')).write_text(compiled.stderr)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)
        command = prefix + [str(binary)] + (['red-v3'] if args.red_v3 else [])
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        (out / (name + '.stdout')).write_text(result.stdout)
        (out / (name + '.stderr')).write_text(result.stderr)
        actual = dict(row.split(' ') for row in result.stdout.splitlines())
        failures = [key for key, value in actual.items() if value != '1']
        expected_failures = ['production-bound-codec-baseline', 'production-bound-reject-missing-codec-baseline'] if args.red_v3 else []
        cases = 2 if args.red_v3 else 288
        valid = result.returncode == 0 and len(actual) == len(result.stdout.splitlines()) == cases and failures == expected_failures
        evidence.append({'target': name, 'cases': len(actual), 'passed': len(actual) - len(failures),
                         'failures': failures, 'exit': result.returncode,
                         'expected_red': args.red_v3, 'expected_red_reproduced': args.red_v3 and valid,
                         'compile_argv': argv, 'binary_sha256': sha(binary),
                         'stdout_sha256': sha(out / (name + '.stdout')),
                         'stderr_sha256': sha(out / (name + '.stderr'))})
        if not valid:
            (out / 'result.json').write_text(json.dumps({'model_only': True, 'board_tested': False,
                                                       'targets': evidence}, indent=2) + '\n')
            raise RuntimeError(f'{name}: unexpected model results {failures}; cases={len(actual)}; {result.stderr}')
    receipt = {'model_only': True, 'board_tested': False,
               'actual_production_source_sha256': sha(source),
               'parser_sha256': sha(source.parent / 'guard-parser.h'),
               'model_source_sha256': sha(HERE / 'clock-stage-model.c'),
               'test_sha256': sha(Path(__file__)), 'expected_red': args.red_v3,
               'real_sysfs_acceptance_tested': False, 'hardware_start_attempted': False,
               'runtime_stop_proof_tested': False,
               'scope': 'Actual production main/collect stage wiring reaches intentionally failing proc/devices read only after the clock count/topology gates pass; all sysfs/proc cache data are synthetic',
               'targets': evidence}
    (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'expected_red': args.red_v3, 'cases_per_target': cases,
                      'targets': [{k: row[k] for k in ('target', 'passed', 'failures')} for row in evidence]}))


if __name__ == '__main__':
    main()
