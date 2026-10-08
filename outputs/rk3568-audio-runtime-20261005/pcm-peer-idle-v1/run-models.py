#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile the actual helper main with external syscall boundaries, then execute."""
from pathlib import Path
import argparse
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME = HERE.parent
UAPI = ROOT / 'third_party/linux-rk3588/include/uapi/sound/asound.h'
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
UAPI_SHA = '138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447'
WRAPS = ['sigemptyset', 'sigaction', 'sigaddset', 'sigprocmask', 'alarm', 'open',
         'fstat', 'ioctl', 'close', 'openat', 'read', 'write', 'syscall', 'fcntl', 'system']


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Need ordinary file: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def normal_trace(open_first, close_first):
    steps = ['empty-action', 'action', 'empty-unblock', 'add', 'unblock', 'alarm5',
             'ctl-open', 'ctl-stat', 'card-info', 'ctl-close']
    for s in [open_first, 'c' if open_first == 'p' else 'p']:
        steps += [s + '-' + name for name in ['open', 'stat', 'version', 'info', 'full', 'exact', 'params', 'setup']]
    other = 'c' if close_first == 'p' else 'p'
    steps += [close_first + '-' + name for name in ['free', 'open-state', 'close']]
    steps += [other + '-peer-setup'] + [other + '-' + name for name in ['free', 'open-state', 'close']] + ['alarm0']
    return steps


def cases(red):
    result = []
    for op, close in itertools.product('pc', repeat=2):
        base = {'open_first': op, 'close_first': close}
        result.append(dict(base, name=op + close + '-normal'))
        if red:
            continue
        trace = normal_trace(op, close)
        stages = [name for name in trace if not name.startswith('alarm')]
        for stage in stages:
            for error in [-5, -4]:
                result.append(dict(base, name=op + close + '-' + stage + '-' + str(error), faults=stage + ':' + str(error)))
            if stage not in ['ctl-open', 'p-open', 'c-open']:
                result.append(dict(base, name=op + close + '-' + stage + '-positive', faults=stage + ':1'))
        payloads = {'ctl-stat': ['regular', 'major'], 'card-info': ['card', 'usb', 'unterminated', 'tail']}
        for s in 'pc':
            payloads[s + '-stat'] = ['regular', 'major']
            payloads[s + '-version'] = ['wrong']
            payloads[s + '-info'] = ['card', 'device', 'subdevice', 'stream', 'id', 'name', 'short',
                                      'id-unterm', 'name-unterm', 'subname-unterm', 'control', 'count', 'avail']
            payloads[s + '-full'] = ['mask-empty', 'interval-empty', 'inverted', 'open-singleton', 'no-rate', 'no-mask']
            for stage in ['exact', 'params']:
                payloads[s + '-' + stage] = ['interval' + str(n) for n in [0, 1, 2, 3, 5, 6, 7, 9, 10]]
                payloads[s + '-' + stage] += ['mask' + str(n) for n in range(3)] + ['extra' + str(n) for n in range(3)]
                payloads[s + '-' + stage] += ['openmin', 'openmax', 'empty', 'wide']
            payloads[s + '-setup'] = ['running', 'prepared', 'wrong', 'appl', 'hw']
            payloads[s + '-open-state'] = ['running', 'prepared', 'wrong']
        other = 'c' if close == 'p' else 'p'
        payloads[other + '-peer-setup'] = ['running', 'prepared', 'wrong', 'appl', 'hw']
        for stage, variants in payloads.items():
            for variant in variants:
                result.append(dict(base, name=op + close + '-' + stage + '-' + variant, bad=stage + ':' + variant))
        # A primary failure plus independently failing cleanup calls must all be
        # reached once, without changing the first error or abandoning the peer.
        for primary in [close + '-free', close + '-open-state', other + '-peer-setup']:
            secondary = [other + '-free', other + '-close']
            if primary != other + '-peer-setup':
                secondary += [close + '-close']
            for extra in secondary:
                result.append(dict(base, name=op + close + '-double-' + primary + '-' + extra,
                                   faults=primary + ':-5,' + extra + ':-12'))
        second = 'c' if op == 'p' else 'p'
        for extra in [op + '-free', op + '-close', second + '-close']:
            result.append(dict(base, name=op + close + '-second-params-double-' + extra,
                               faults=second + '-params:-5,' + extra + ':-12'))
    if not red:
        valid = ['--card', '1', '--open-first', 'playback', '--close-first', 'capture']
        invalid = [[], valid[:-1], valid + ['extra'], ['--card', '-1'] + valid[2:],
                   ['--card', '8'] + valid[2:], ['--card', '01'] + valid[2:]]
        for index in [0, 2, 4]:
            changed = valid.copy(); changed[index] = '--unknown'; invalid.append(changed)
        for index in [1, 3, 5]:
            for value in ['', 'x', 'Playback', 'capture0']:
                changed = valid.copy(); changed[index] = value; invalid.append(changed)
        for index, argv in enumerate(invalid):
            result.append({'name': 'invalid-' + str(index), 'argv': argv, 'invalid': True})
        result.append({'name': 'card-zero', 'card': '0', 'open_first': 'p', 'close_first': 'p'})
        result.append({'name': 'card-seven', 'card': '7', 'open_first': 'c', 'close_first': 'c'})
        result.append({'name': 'real-default-SIGALRM-inherited-ignore-and-block',
                       'open_first': 'p', 'close_first': 'c', 'deadline': 'c-params'})
    return result


def execute(directory, label, argv, env=None, timeout=60):
    started = time.monotonic()
    result = subprocess.run(argv, capture_output=True, env=env, timeout=timeout)
    (directory / (label + '.stdout')).write_bytes(result.stdout)
    (directory / (label + '.stderr')).write_bytes(result.stderr)
    save(directory / (label + '.command.json'), {'argv': argv, 'exit': result.returncode})
    return result, time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['red', 'green'], required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source = args.source or (RUNTIME / 'pcm-config.c' if args.phase == 'red' else HERE / 'pcm-peer-idle.c')
    out = args.out.absolute()
    if out.parent.resolve() != HERE or out.exists() or out.is_symlink() or sha(UAPI) != UAPI_SHA:
        raise ValueError('Fresh owned output and exact locked UAPI required')
    out.mkdir()
    shutil.copy2(source, out / 'source-under-test.c')
    shutil.copy2(HERE / 'model.c', out / 'model.c')
    shutil.copy2(UAPI, out / 'asound.h')
    if (HERE / 'parameters.h').exists():
        shutil.copy2(HERE / 'parameters.h', out / 'parameters.h')
    common = ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fno-builtin', '-fno-ident',
              '-DALSA_LOCKED_UAPI="' + str(out / 'asound.h') + '"', '-D__user=', '-D__force=']
    environments = [('host', 'gcc', [])] if args.phase == 'red' else [
        ('host', 'gcc', []), ('asan-ubsan', 'gcc', ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']),
        ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-static', '-Wl,--build-id=none'])]
    entries = cases(args.phase == 'red')
    results = {}
    for name, compiler, flags in environments:
        directory = out / name; directory.mkdir()
        obj = directory / 'source.o'; binary = directory / 'wrapped-peer'
        commands = [([compiler] + common + flags + ['-Dmain=peer_main', '-c', str(out / 'source-under-test.c'), '-o', str(obj)], 'compile-source'),
                    ([compiler] + common + flags + [str(out / 'model.c'), str(obj)] + ['-Wl,--wrap=' + symbol for symbol in WRAPS] + ['-o', str(binary)], 'link-model')]
        for argv, label in commands:
            result, _ = execute(directory, label, argv)
            if result.returncode:
                raise RuntimeError(result.stderr.decode())
        rows = []
        for index, case in enumerate(entries):
            option = case.get('argv') or ['--card', case.get('card', '1'), '--open-first', 'capture' if case.get('open_first') == 'c' else 'playback',
                                          '--close-first', 'capture' if case.get('close_first') == 'c' else 'playback']
            if case.get('invalid'):
                option = case['argv']
            argv = ([str(QEMU)] if name == 'aarch64-qemu' else []) + [str(binary)] + option
            env = dict(os.environ)
            env.update(PEER_FAULTS=case.get('faults', ''), PEER_BAD=case.get('bad', ''))
            for key in ['PEER_INVALID', 'PEER_DEADLINE']:
                env.pop(key, None)
            if case.get('invalid'): env['PEER_INVALID'] = '1'
            if case.get('deadline'): env['PEER_DEADLINE'] = case['deadline']
            env['ASAN_OPTIONS'] = 'detect_leaks=0:abort_on_error=1'
            env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
            result, elapsed = execute(directory, 'case-' + str(index), argv, env=env, timeout=9)
            stdout, stderr = result.stdout.decode(), result.stderr.decode()
            if case.get('deadline'):
                passed = result.returncode == -14 and 4.3 <= elapsed <= 8.5
                row = {'case': case, 'passed': passed, 'exit': result.returncode, 'elapsed_seconds': elapsed}
            else:
                match = re.search(r'^PEER_MODEL (.+)$', stderr, re.M)
                model = json.loads(match.group(1)) if match else None
                passed = bool(model and model['violations'] == 0)
                if case.get('faults') or case.get('bad'):
                    first = re.search(r'PCM_PEER_FAILED seq=(\d+) name=(\S+) errno=(\d+)', stderr)
                    passed = passed and result.returncode == 2 and bool(first) and first.group(2) == model['first_event'] and int(first.group(3)) == model['first_errno']
                    for item in case.get('faults', '').split(','):
                        if item: passed = passed and item.split(':')[0] in model['trace'].split(',')
                elif case.get('invalid'):
                    passed = passed and result.returncode == 2 and model['events'] == 0
                else:
                    passed = passed and result.returncode == 0 and 'PCM_PEER_IDLE_VERIFIED_NO_START' in stdout and model['trace'].split(',') == normal_trace(case['open_first'], case['close_first'])
                operations = re.findall(r'^PCM_PEER_OP seq=(\d+) ', stdout, re.M)
                if not case.get('invalid'):
                    passed = passed and operations == [str(n) for n in range(1, model['events'] + 1)] if model else False
                row = {'case': case, 'passed': bool(passed), 'exit': result.returncode, 'model': model}
            rows.append(row)
        results[name] = {'source_object_sha256': sha(obj), 'binary_sha256': sha(binary),
                         'cases': rows, 'passed': sum(row['passed'] for row in rows), 'total': len(rows)}
        print(name + ': ' + str(results[name]['passed']) + '/' + str(len(rows)), flush=True)
    record = {'phase': args.phase, 'source_sha256': sha(out / 'source-under-test.c'),
              'parameters_header_sha256': sha(out / 'parameters.h') if (out / 'parameters.h').exists() else None,
              'wrapper_sha256': sha(out / 'model.c'), 'runner_sha256': sha(Path(__file__)), 'locked_UAPI_sha256': UAPI_SHA,
              'results': results, 'model_only': True, 'board_tested': False, 'real_ALSA_access': False,
              'boundary': 'Actual helper main, external syscall boundary models; actual SIGALRM test covers interruptible pause only. No kernel/PM/DMA/shared-cache proof or hardware START permission.'}
    save(out / 'result.json', record)
    failures = sum(row['total'] - row['passed'] for row in results.values())
    if args.phase == 'red':
        if failures != 4: raise ValueError('Expected all four absent-peer-flow red cases')
    elif failures:
        raise ValueError('Failed cases: ' + str(failures))


if __name__ == '__main__':
    main()
