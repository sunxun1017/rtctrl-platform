#!/usr/bin/env python3
"""Build a static reboot-only helper after the actual-main boundary tests pass."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'v[1-9][0-9]*', args.revision):
        raise ValueError('Invalid revision')
    build = HERE / 'build' / ('production-' + args.revision)
    if build.exists() or build.is_symlink() or any(p.is_symlink() for p in build.parents):
        raise ValueError('Refusing existing or symlink output')
    source = HERE / 'normal-reboot.c'
    tests_path = HERE / 'build/tests-v3/result.json'
    tests = json.loads(tests_path.read_text())
    if tests['passed'] != 32 or not all(x['passed'] for x in tests['cases']) or tests['source_sha256'] != sha(source):
        raise ValueError('Actual-main tests do not bind current production source')
    compiler = subprocess.check_output(['aarch64-linux-gnu-gcc', '--version'], text=True).splitlines()[0]
    if compiler != 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0':
        raise ValueError('Unexpected compiler')
    build.mkdir(parents=True)
    executable = build / 'normal-reboot'
    command = ['aarch64-linux-gnu-gcc', '-static', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', str(source), '-o', str(executable)]
    result = subprocess.run(command, capture_output=True, text=True)
    (build / 'compile.log').write_text(result.stdout + result.stderr)
    if result.returncode != 0:
        raise ValueError('Compilation failed')
    header = subprocess.check_output(['aarch64-linux-gnu-readelf', '-h', str(executable)], text=True)
    program = subprocess.check_output(['aarch64-linux-gnu-readelf', '-l', str(executable)], text=True)
    symbols = subprocess.check_output(['aarch64-linux-gnu-nm', str(executable)], text=True)
    (build / 'elf.txt').write_text(header + program)
    test_wrappers = ['geteuid', 'getpid', 'uname', 'readlink', 'statfs', 'fflush', 'reboot']
    if 'AArch64' not in header or 'INTERP' in program or any('__wrap_' + x in symbols for x in test_wrappers):
        raise ValueError('Production ELF contract failed')
    qemu = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
    refused = subprocess.run([str(qemu), str(executable)], capture_output=True, text=True, timeout=5)
    if refused.returncode != 2 or 'Only --request is accepted' not in refused.stderr:
        raise ValueError('Production no-argument refusal failed')
    manifest = {'source_sha256': sha(source), 'builder_sha256': sha(Path(__file__)), 'test_sha256': sha(tests_path),
                'compiler': compiler, 'compile_argv': command, 'compile_exit_code': result.returncode,
                'elf_sha256': sha(executable), 'elf_bytes': executable.stat().st_size,
                'static_aarch64': True, 'test_wrappers_in_production': False, 'actual_main_cases_passed': 32,
                'production_no_argument_refusal': True, 'normal_reboot_board_tested': False,
                'only_command': 'LINUX_REBOOT_CMD_RESTART', 'external_ram_guard_required': True}
    (build / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))

if __name__ == '__main__':
    main()
