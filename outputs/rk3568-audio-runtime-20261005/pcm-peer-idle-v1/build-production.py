#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build/audit a static AArch64 peer-idle executable; run only invalid arguments."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
ALLOWED_IMPORTS = {'__errno_location', 'alarm', 'close', 'fprintf', 'fstat', 'ioctl',
                   'memcmp', 'memset', 'open', 'printf', 'puts', 'sigaction', 'sigaddset',
                   'sigemptyset', 'sigprocmask', 'snprintf', 'strcmp', 'strlen', 'stderr',
                   '__stack_chk_fail', '__stack_chk_guard', '__printf_chk',
                   '__fprintf_chk', '__snprintf_chk'}


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Ordinary input required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def run(out, name, argv, expected=0):
    result = subprocess.run(argv, capture_output=True, timeout=30)
    (out / (name + '.stdout')).write_bytes(result.stdout)
    (out / (name + '.stderr')).write_bytes(result.stderr)
    save(out / (name + '.command.json'), {'argv': argv, 'exit': result.returncode})
    if result.returncode != expected:
        raise RuntimeError(name + ': ' + result.stderr.decode())
    return result


def protected():
    record = json.loads((HERE / 'input-manifest.json').read_text())
    for name, digest in record['external_inputs_sha256'].items():
        if sha(ROOT / name) != digest or sha(HERE / 'inputs' / name) != digest:
            raise ValueError('Locked original/copy changed: ' + name)
    if sha(HERE / 'parameters.h') != record['parameters_header_sha256']:
        raise ValueError('Byte-exact baseline parameter helpers changed')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=HERE / 'production-v2')
    args = parser.parse_args()
    out = args.out.absolute()
    if out.parent.resolve() != HERE or out.exists() or out.is_symlink():
        raise ValueError('Fresh owned build directory required')
    inputs = protected()
    models = args.models.resolve(strict=True)
    if models.parent != HERE:
        raise ValueError('Owned actual model run required')
    proof = json.loads((models / 'result.json').read_text())
    test_spec = importlib.util.spec_from_file_location('peer_model_runner', HERE / 'run-models.py')
    test_module = importlib.util.module_from_spec(test_spec)
    test_spec.loader.exec_module(test_module)
    expected_cases = test_module.cases(False)
    if proof['phase'] != 'green' or proof['source_sha256'] != sha(HERE / 'pcm-peer-idle.c') or \
            proof['parameters_header_sha256'] != sha(HERE / 'parameters.h') or \
            proof['wrapper_sha256'] != sha(HERE / 'model.c') or proof['runner_sha256'] != sha(HERE / 'run-models.py') or \
            set(proof['results']) != {'host', 'asan-ubsan', 'aarch64-qemu'} or \
            any(row['passed'] != row['total'] or row['total'] != len(expected_cases) or \
                [item['case'] for item in row['cases']] != expected_cases or not all(item['passed'] for item in row['cases'])
                for row in proof['results'].values()):
        raise ValueError('Current actual main must pass all three environments')
    for name, row in proof['results'].items():
        if sha(models / name / 'source.o') != row['source_object_sha256'] or \
                sha(models / name / 'wrapped-peer') != row['binary_sha256']:
            raise ValueError('Executed model object/binary changed')
    compiler = subprocess.check_output(['aarch64-linux-gnu-gcc', '--version'], text=True).splitlines()[0]
    if compiler != 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0':
        raise ValueError('Compiler differs from locked Image')
    out.mkdir()
    for name in ['pcm-peer-idle.c', 'parameters.h']:
        shutil.copy2(HERE / name, out / name)
    shutil.copy2(HERE / 'inputs/third_party/linux-rk3588/include/uapi/sound/asound.h', out / 'asound.h')
    common = ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fno-builtin', '-fno-ident',
              '-fstack-protector-strong', '-DALSA_LOCKED_UAPI="' + str(out / 'asound.h') + '"', '-D__user=', '-D__force=']
    obj, binary = out / 'pcm-peer-idle.o', out / 'pcm-peer-idle'
    run(out, 'compile', ['aarch64-linux-gnu-gcc'] + common + ['-c', str(out / 'pcm-peer-idle.c'), '-o', str(obj)])
    imports_result = run(out, 'undefined-imports', ['aarch64-linux-gnu-nm', '-u', str(obj)])
    imports = {line.split()[-1] for line in imports_result.stdout.decode().splitlines() if line.strip()}
    if not imports or not imports <= ALLOWED_IMPORTS:
        raise ValueError('Unexpected production imports: ' + str(imports - ALLOWED_IMPORTS))
    run(out, 'link-static', ['aarch64-linux-gnu-gcc', '-static', '-Wl,--build-id=none', str(obj), '-o', str(binary)])
    data = binary.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', data, 16) != (2, 183):
        raise ValueError('Need static ELF64 LE AArch64 ET_EXEC')
    headers = run(out, 'ELF', ['aarch64-linux-gnu-readelf', '-h', '-lW', str(binary)]).stdout.decode()
    dynamic = run(out, 'dynamic', ['aarch64-linux-gnu-readelf', '-d', str(binary)]).stdout.decode()
    if 'INTERP' in headers or 'There is no dynamic section' not in dynamic:
        raise ValueError('Need genuinely static deployment binary')
    run(out, 'instructions', ['aarch64-linux-gnu-objdump', '-dr', str(obj)])
    # No valid device invocation on the host; rejected CLI exits before even signal/device boundaries.
    for index, argv in enumerate([[], ['--card', '8', '--open-first', 'playback', '--close-first', 'capture'],
                                  ['--card', '1', '--open-first', 'wrong', '--close-first', 'capture']]):
        run(out, 'actual-argument-rejection-' + str(index), [str(QEMU), str(binary)] + argv, expected=2)
    if protected() != inputs:
        raise ValueError('Original inputs changed during build')
    record = {'exit': 0, 'source_sha256': sha(HERE / 'pcm-peer-idle.c'),
              'parameters_header_sha256': sha(HERE / 'parameters.h'), 'input_manifest_sha256': sha(HERE / 'input-manifest.json'),
              'model_result_sha256': sha(models / 'result.json'),
              'source_object_sha256': sha(obj), 'binary_bytes': len(data), 'binary_sha256': sha(binary),
              'binary_crc32': '%08x' % zlib.crc32(data), 'compiler': compiler, 'imports': sorted(imports),
              'builder_sha256': sha(Path(__file__)), 'source_static_ABI_assertions_passed': True,
              'static_AArch64_ELF': True, 'actual_invalid_argument_QEMU_runs': 3,
              'old_inputs_unchanged': True, 'model_environments': {name: [row['passed'], row['total']] for name, row in proof['results'].items()},
              'board_tested': False, 'kernel_PM_DMA_or_shared_sysclk_proven': False,
              'START_permission': False, 'independent_review_completed': False, 'frozen': False}
    save(out / 'manifest.json', record)
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
