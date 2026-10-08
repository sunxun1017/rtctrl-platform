#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile actual helper unchanged, test externally observable syscall contracts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UAPI = ROOT / 'third_party/linux-rk3588/include/uapi/sound/asound.h'
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
WRAPS = ['open', 'fstat', 'ioctl', 'close', 'poll', '__poll_chk', 'read', '__read_chk', 'write', 'clock_gettime', 'setitimer', 'fwrite']
EXPECTED_UAPI = '138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    assert sha(UAPI) == EXPECTED_UAPI
    output = HERE / 'build' / ('tests-' + args.label)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.source, output / 'source.c')
    shutil.copy2(HERE / 'test-wrapper.c', output / 'wrappers.c')
    shutil.copy2(UAPI, output / 'asound-locked.h')
    results = {}
    scenarios = ['normal', 'short-io', 'io-eintr', 'io-eagain', 'poll-eintr', 'open-control', 'stat-control', 'card-info', 'wrong-major', 'wrong-card', 'card-unterminated', 'duplicate-card', 'close-control', 'open-pcm', 'stat-pcm', 'version', 'wrong-version', 'info', 'wrong-pcm', 'refine', 'params', 'params-mismatch', 'sw-params', 'prepare', 'bad-prepared', 'start', 'status', 'xrun', 'xrun-cleanup-errors', 'poll-error', 'poll-timeout', 'poll-hangup', 'poll-xrun', 'io-error', 'io-zero', 'io-misaligned', 'io-oversize', 'io-always-eagain', 'state-xrun', 'no-hardware-progress', 'signal-stop', 'drop', 'free', 'close-pcm', 'close-eintr', 'clock', 'timer', 'real-timer']
    scenarios += ['other-control', 'wrong-driver', 'wrong-name', 'wrong-longname', 'sw-mismatch', 'prepare-eintr', 'start-eintr', 'drop-eintr', 'free-eintr', 'signal-io']
    scenarios += ['log-capacity', 'minimum-target', 'maximum-target', 'example-target']
    scenarios += ['output-deadline']
    success = {'normal', 'short-io', 'io-eintr', 'io-eagain', 'poll-eintr', 'other-control'}
    success |= {'minimum-target', 'maximum-target', 'example-target'}
    failed = False
    for mode, compiler, flags, launch in [('host', 'gcc', ['-O2', '-D_FORTIFY_SOURCE=2'], []), ('sanitized', 'gcc', ['-O1', '-D_FORTIFY_SOURCE=2', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'], []), ('aarch64', 'aarch64-linux-gnu-gcc', ['-O2', '-D_FORTIFY_SOURCE=2', '-static'], [str(QEMU)])]:
        binary = output / ('helper-' + mode)
        argv = [compiler, '-std=gnu11', '-O0', '-Wall', '-Wextra', '-Werror', *flags, '-D__user=', '-D__force=', '-DALSA_LOCKED_UAPI="asound-locked.h"', '-I' + str(output), str(output / 'source.c'), str(output / 'wrappers.c'), *['-Wl,--wrap=' + n for n in WRAPS], '-o', str(binary)]
        built = subprocess.run(argv, capture_output=True, text=True)
        (output / (mode + '-compile.stdout')).write_text(built.stdout)
        (output / (mode + '-compile.stderr')).write_text(built.stderr)
        record = dict(compile_exit=built.returncode, argv=argv, cases=[])
        if built.returncode: failed = True
        else:
            record['binary_sha256'] = sha(binary)
            for direction in ['playback', 'capture']:
                for case in scenarios:
                    frame_target = {'minimum-target':1024, 'maximum-target':47872, 'example-target':24576}.get(case, 4096)
                    params = ['--configure', '--card', '0', '--stream', direction] if args.baseline else ['--card-id', 'rockchiprk809co', '--stream', direction, '--frames', str(frame_target), '--timeout-ms', '100' if case == 'real-timer' else '3000']
                    env = dict(__import__('os').environ, PCM_TEST_CASE=case)
                    if args.baseline: env['PCM_TEST_BASELINE'] = '1'
                    started = time.monotonic()
                    ran = subprocess.run([*launch, str(binary), *params], env=env, capture_output=True, text=True, timeout=12)
                    elapsed = time.monotonic() - started
                    stem = mode + '-' + direction + '-' + case
                    (output / (stem + '.stdout')).write_text(ran.stdout)
                    (output / (stem + '.stderr')).write_text(ran.stderr)
                    calls = []
                    for line in ran.stderr.splitlines():
                        if line.startswith('TEST_CALL '):
                            _, name, value = line.split(); calls.append((name, int(value)))
                    names = [n for n,v in calls]
                    wanted = case in success
                    ok = ran.returncode == (0 if wanted else 2) and 'AddressSanitizer' not in ran.stderr and 'runtime error:' not in ran.stderr
                    if wanted:
                        ok &= 'PCM_BOUNDED_IO_COMPLETE' in ran.stdout and names.count('start') == 1 and names.count('drop') == 1 and names.count('free') == 1 and names.count('close-pcm') == 1
                        sequence = ['params', 'sw-params', 'prepare', 'start', 'drop', 'free', 'close-pcm']
                        ok &= all(n in names for n in sequence) and [names.index(n) for n in sequence] == sorted(names.index(n) for n in sequence)
                        ok &= ('read' if direction == 'capture' else 'write') in names and ('write' if direction == 'capture' else 'read') not in names
                        ok &= 'frames=' + str(frame_target) in ran.stdout and 'card=7' in ran.stdout
                        if direction == 'capture': ok &= 'samples=' + str(frame_target*2) + ' zeros=' + str(frame_target) in ran.stdout
                    if 'params' in names:
                        ok &= all(n in names for n in ['drop', 'free', 'close-pcm']) and names.count('drop') == 1 and names.count('free') == 1 and names.count('close-pcm') == 1 and names.index('drop') < names.index('free') < names.index('close-pcm')
                    if 'open-pcm' in names and case != 'open-pcm': ok &= names.count('close-pcm') == 1
                    if 'start' in names and 'close-pcm' in names:
                        lines = ran.stderr.splitlines()
                        active = lines[lines.index('TEST_CALL start 1'):lines.index('TEST_CALL close-pcm 1000')]
                        ok &= not any(line.startswith(('PCM_STAGE', 'PCM_ERROR')) for line in active)
                    if not wanted: ok &= 'PCM_FIRST_ERROR' in ran.stderr and 'PCM_BOUNDED_IO_COMPLETE' not in ran.stdout
                    if case == 'start': ok &= 'stage=START errno=121' in ran.stderr
                    if case in ['xrun', 'xrun-cleanup-errors']: ok &= 'errno=32' in ran.stderr and names.count('prepare') == names.count('start') == 1
                    if case in ['poll-timeout', 'io-always-eagain', 'real-timer', 'output-deadline']: ok &= 'errno=110' in ran.stderr
                    if case == 'real-timer': ok &= elapsed < 2 and names.count('drop') == names.count('free') == names.count('close-pcm') == 1
                    if case == 'log-capacity': ok &= 'stage=LOG_CAPACITY errno=105' in ran.stderr and names.count('drop') == names.count('free') == names.count('close-pcm') == 1
                    failed |= not ok
                    record['cases'].append(dict(name=direction + '/' + case, passed=bool(ok), exit=ran.returncode, elapsed=elapsed, calls=calls, stdout_sha256=hashlib.sha256(ran.stdout.encode()).hexdigest(), stderr_sha256=hashlib.sha256(ran.stderr.encode()).hexdigest()))
            if not args.baseline:
                valid = ['--card-id', 'rockchiprk809co', '--stream', 'playback', '--frames', '24576', '--timeout-ms', '5000']
                inputs = [[], valid + ['extra']]
                for index, values in [(1, ['other']), (3, ['duplex', 'invalid']), (5, ['0', '1023', '1025', '48000', '48128', '-1024', '184467440737095516160', ' 1024', '+1024']), (7, ['99', '10001', 'invalid'])]:
                    for value in values:
                        altered = list(valid); altered[index] = value; inputs.append(altered)
                for index, params in enumerate(inputs):
                    ran = subprocess.run([*launch, str(binary), *params], env=dict(__import__('os').environ, PCM_TEST_CASE='normal'), capture_output=True, text=True, timeout=5)
                    name = mode + '-invalid-' + str(index)
                    (output / (name + '.stdout')).write_text(ran.stdout); (output / (name + '.stderr')).write_text(ran.stderr)
                    ok = ran.returncode == 2 and 'usage:' in ran.stderr and 'TEST_CALL' not in ran.stderr
                    failed |= not ok
                    record['cases'].append(dict(name='invalid/' + str(index), passed=ok, exit=ran.returncode, argv=params, stdout_sha256=hashlib.sha256(ran.stdout.encode()).hexdigest(), stderr_sha256=hashlib.sha256(ran.stderr.encode()).hexdigest()))
        results[mode] = record
    result = dict(source_sha256=sha(output / 'source.c'), wrapper_sha256=sha(output / 'wrappers.c'), uapi_sha256=sha(UAPI), script_sha256=sha(Path(__file__)), runs=results, passed=not failed, baseline=args.baseline, board_tested=False, real_alsa_device_access=False, actual_bounded_transfer=False, boundary='Entire unchanged actual C program with linker syscall wrappers; real signal deadline case returns through cleanup, no actual sound device')
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(result=str(output / 'result.json'), passed=not failed, runs={mode:dict(compile=r['compile_exit'], passed=sum(c['passed'] for c in r['cases']), total=len(r['cases'])) for mode,r in results.items()})))
    return int(failed)
if __name__ == '__main__': raise SystemExit(main())
