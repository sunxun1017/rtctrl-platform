#!/usr/bin/env python3
"""Record one read-only source/model check, with no compiler or kernel operation."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
MANIFEST_SHA = '07b6e6cd407d6c0e5d0772929d7a05fb9995bf8aaa3a09a5ccfc3bc869a5e84e'
RUNNER_SHA = 'ca0850a477ebbdca9354af9208e097a16465656d290e749adfc6a785301fd474'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Ordinary file required')
    return {'sha256': sha(path), 'bytes': path.stat().st_size, 'mode': stat.S_IMODE(path.stat().st_mode)}


def main():
    if sha(HERE / 'run-model.py') != RUNNER_SHA or sha(HERE / 'model-v1/input-manifest.json') != MANIFEST_SHA:
        raise ValueError('Submitted model/runner identity changed')
    output = HERE / 'preparation-readback-v1'
    output.mkdir(exist_ok=False)
    for name in ['run-model.py', 'prepare-model.py', 'record-preparation.py', 'test-params-caller.c', 'params-api.h', 'params-events.h', 'README.md']:
        shutil.copy2(HERE / name, output / name)
    argv = [sys.executable, '-B', str(HERE / 'run-model.py'), '--model', 'model-v1',
        '--manifest-sha256', MANIFEST_SHA, '--attempt', 'readonlycheck', '--check']
    result = subprocess.run(argv, capture_output=True, timeout=30)
    (output / 'precheck.stdout').write_bytes(result.stdout)
    (output / 'precheck.stderr').write_bytes(result.stderr)
    command = {'argv': argv, 'exit': result.returncode,
        'stdout': metadata(output / 'precheck.stdout'), 'stderr': metadata(output / 'precheck.stderr')}
    (output / 'precheck.command.json').write_text(json.dumps(command, indent=2) + '\n')
    if result.returncode or result.stderr:
        raise ValueError('Read-only source/model check failed; raw attempt preserved')
    actual = json.loads(result.stdout)
    if actual.get('status') != 'SOURCE_MODEL_READONLY_PRECHECK' or actual.get('model_executed') is not False or actual.get('compiler_executed') is not False:
        raise ValueError('Unexpected precheck scope')
    excluded = {output / 'file-manifest.json', output / 'receipt.json'}
    files = {p.relative_to(HERE).as_posix(): metadata(p) for p in sorted(HERE.rglob('*')) if p.is_file() and p not in excluded}
    manifest = output / 'file-manifest.json'
    manifest.write_text(json.dumps({'scope': 'OWNED_PREPARED_BYTES_FINGERPRINT_NOT_MODEL_RESULT_OR_SEAL', 'files': files}, indent=2) + '\n')
    receipt = {'status': 'PREPARED_PARENT_REVIEW_PENDING_NO_MODEL_EXECUTION',
        'read_only_precheck': command, 'precheck_actual_result': actual,
        'file_manifest': metadata(manifest), 'ordinary_fingerprint_count': len(files),
        'model_manifest_sha256': MANIFEST_SHA, 'runner_sha256': RUNNER_SHA,
        'model_compiled': False, 'model_executed': False, 'production_modified': False,
        'Kbuild_executed': False, 'board_tested': False, 'duplex_START_authorized': False}
    path = output / 'receipt.json'
    path.write_text(json.dumps(receipt, indent=2) + '\n')
    for rel, item in files.items():
        if metadata(HERE / rel) != item:
            raise ValueError('Prepared byte readback changed: ' + rel)
    print(json.dumps({'receipt_sha256': sha(path), 'file_manifest_sha256': sha(manifest),
        'ordinary_fingerprint_count': len(files), 'model_executed': False}))


if __name__ == '__main__':
    main()
