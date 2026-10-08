#!/usr/bin/env python3
"""Fresh finite gauge parameter regression; never access a board or PMIC."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'build/root-v5-fresh-v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_freeze(version, receipt_sha, manifest_sha, count):
    directory = HERE / ('sealed-' + version)
    assert sha(directory / 'receipt.json') == receipt_sha
    assert sha(directory / 'manifest.json') == manifest_sha
    items = json.loads((directory / 'manifest.json').read_text())['files_sha256']
    assert len(items) == count
    for name, expected in items.items():
        path = directory / name
        assert path.resolve().is_relative_to(directory) and sha(path) == expected, name
    return items


def main():
    assert not OUT.exists() and not OUT.is_symlink()
    old = check_freeze('v4', 'ab2dbc82f1c3ee000fa1880feea3d711efb7df170d990ca2e386dca9291b925e',
                       '7b5c7ab8ac9523b07535319e6e936417c70dd77ad093e658abec4fa1d35b4c6a', 224)
    new = check_freeze('v5', 'cd9576ee289f2ea80f756c25b339b104202e8f84470253b03a5450e92170b689',
                       'ad74ef00bdfc83003c42b939b1c5f8ddeaaf5b782382d3c092b93a542a4281d5', 134)
    for name, expected in new.items():
        if name.startswith(('candidate-v5/', 'model-v5/')):
            assert sha(HERE / name) == expected, name
    assert sha(HERE / 'candidate-v4/drivers/power/supply/rk817_battery.c') == \
        '60214a61168143700b06e9f2aad08697ef6be6f2181d9b8a427336aa10709efc'
    OUT.mkdir(parents=True)
    result = {'passed': False, 'fresh_compilation': True, 'board_tested': False,
              'old_files_verified': len(old), 'new_files_verified': len(new),
              'battery_parameters': 'Unknown, user will supply later',
              'accepted_for_board': False, 'runs': {}, 'evidence_sha256': {}}
    pipeline = HERE / 'model-v5'
    for name, source, failures in [('red-v4-voltage', '../candidate-v4', 32),
                                   ('green-v5-voltage', '../candidate-v5', 0)]:
        output = OUT / name
        argv = [sys.executable, '-B', str(pipeline / 'test-model.py'),
                '--source', source + '/drivers/power/supply/rk817_battery.c',
                '--output', str(output), '--candidate']
        run = subprocess.run(argv, capture_output=True, timeout=120)
        (OUT / (name + '-pipeline.stdout')).write_bytes(run.stdout)
        (OUT / (name + '-pipeline.stderr')).write_bytes(run.stderr)
        assert run.returncode == 0 and not run.stderr, run.stderr.decode(errors='replace')
        report = json.loads((output / 'result.json').read_text())
        authored = json.loads((pipeline / name / 'result.json').read_text())
        assert report['source_sha256'] == authored['source_sha256']
        assert report['units_sha256'] == authored['units_sha256']
        assert report['wrapper_sha256'] == authored['wrapper_sha256']
        for entry in report['results']:
            mode = entry['environment']
            assert entry['passed'] == 191 - failures and entry['failed'] == failures
            assert entry['returncode'] == int(failures != 0)
            assert (output / (mode + '-stdout.txt')).read_bytes() == (pipeline / name / (mode + '-stdout.txt')).read_bytes()
            assert not (output / (mode + '-stderr.txt')).read_bytes()
        result['runs'][name] = report
        print(name + ': fresh 191-case three-environment regression verified', flush=True)
    for path in OUT.rglob('*'):
        if path.is_file():
            result['evidence_sha256'][path.relative_to(OUT).as_posix()] = sha(path)
    result['passed'] = True
    (OUT / 'result.json').write_bytes((json.dumps(result, indent=2) + '\n').encode())
    print('GAUGE_V5_ROOT_FRESH_FINITE_PARAMETER_REGRESSION_VERIFIED', flush=True)


if __name__ == '__main__':
    main()
