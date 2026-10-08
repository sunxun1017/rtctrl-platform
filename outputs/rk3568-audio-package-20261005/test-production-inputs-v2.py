#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real production inputs exercise both package regressions, without a device."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GATE = 'outputs/rk3568-audio-runtime-20261005/build/review-gate-v2.json'
PRODUCTION = 'outputs/rk3568-audio-runtime-20261005/build/integration-v1/'
LINUX_RELEASE = '5.10.160-rt89-g9f9e9d18574d-dirty'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', default='audio-package-v2.py')
    parser.add_argument('--out', required=True)
    parser.add_argument('--old-cli-red', action='store_true')
    args = parser.parse_args()
    assert args.core in ('audio-package.py', 'audio-package-v2.py')
    source = HERE / args.core
    spec = importlib.util.spec_from_file_location('audio_production_regression', source)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    output = core.fresh_directory(args.out)
    cases = []

    def run(name, call):
        try:
            evidence = call()
            cases.append({'name': name, 'passed': True, 'evidence': evidence})
        except Exception as error:
            cases.append({'name': name, 'passed': False,
                          'error': type(error).__name__ + ': ' + str(error)})

    def reject(call, phrase):
        try:
            call()
        except (ValueError, OSError) as error:
            assert phrase in str(error), str(error)
            return str(error)
        raise AssertionError('Invalid input accepted')

    # These are real completed build files. They are never modified by this test.
    gate_data = (ROOT / GATE).read_bytes()
    gate = core.unique_json(gate_data)
    manifest_data = (ROOT / (PRODUCTION + 'manifest.json')).read_bytes()
    manifest = core.unique_json(manifest_data)
    image = (ROOT / (PRODUCTION + 'Image')).read_bytes()
    assert manifest['kernel_release'] == LINUX_RELEASE
    assert core.metadata(image) == {'bytes': 34755072,
        'sha256': 'e48c4295b871623f3c4d0e18470d451b5c344b7e71d021c77f9b0cc297d89955',
        'crc32': 'fb920db9'}
    zero_files = [name for name in gate['files_sha256'] if (ROOT / name).stat().st_size == 0]
    assert zero_files and len(gate['files_sha256']) == 910
    zero_name = zero_files[0]

    def empty_reviewed_log():
        core.verify_hash_map({zero_name: gate['files_sha256'][zero_name]})
        return {'path': zero_name, **core.metadata((ROOT / zero_name).read_bytes())}

    run('real-reviewed-zero-byte-log-accepted', empty_reviewed_log)

    def whole_gate():
        core.verify_hash_map(gate['files_sha256'])
        return {'verified_files': len(gate['files_sha256']), 'zero_byte_files': len(zero_files)}

    run('real-review-gate-all-files-accepted', whole_gate)
    run('real-production-Linux-Image-metadata-accepted',
        lambda: core.validate_image_metadata(manifest, image))
    for release in ('4.19.232', '5.10.160', LINUX_RELEASE + '-wrong', None):
        run('wrong-release-rejected-' + str(release), lambda release=release: reject(
            lambda: core.validate_image_metadata({**manifest, 'kernel_release': release}, image),
            'Expected kernel release'))

    empty = output / 'empty-input'
    core.write_new(empty, b'')
    run('empty-ordinary-file-accepted', lambda: core.metadata(core.read_ordinary(empty)))
    run('empty-JSON-rejected-by-format', lambda: reject(
        lambda: core.unique_json(core.read_ordinary(empty)), 'Expecting value'))
    run('empty-Image-rejected-by-content-binding', lambda: reject(
        lambda: core.validate_image_metadata(manifest, core.read_ordinary(empty)), 'Complete Image content binding'))
    run('empty-ARM64-header-rejected', lambda: reject(
        lambda: core.image_plan(core.read_ordinary(empty), {}, {}), 'ARM64 Image magic/header'))
    nonempty = output / 'nonempty-input'
    core.write_new(nonempty, b'x')
    run('size-upper-bound-retained', lambda: reject(
        lambda: core.read_ordinary(nonempty, limit=0), 'Bounded ordinary file required'))
    run('ordinary-file-type-retained', lambda: reject(
        lambda: core.read_ordinary(output), 'Bounded ordinary file required'))
    link = output / 'symlink-input'
    link.symlink_to(empty)
    run('symlink-path-retained', lambda: reject(
        lambda: core.read_ordinary(link), 'Ordinary repository file required'))

    if args.old_cli_red:
        argv = [sys.executable, '-B', str(HERE / 'build-audio-package.py'),
                '--review-gate', GATE, '--out', str(output / 'must-not-exist')]
        process = subprocess.run(argv, capture_output=True, timeout=60)
        core.write_new(output / 'old-production-cli.stdout', process.stdout)
        core.write_new(output / 'old-production-cli.stderr', process.stderr)
        core.write_new(output / 'old-production-cli.json', core.json_bytes({
            'argv': argv, 'exit_code': process.returncode,
            'output_directory_created': (output / 'must-not-exist').exists(),
            'expected_rejection': 'Bounded ordinary file required'}))
        assert process.returncode == 1 and b'Bounded ordinary file required' in process.stderr
        assert not (output / 'must-not-exist').exists()

    result = {'mode': 'REAL_PRODUCTION_INPUT_REGRESSION_OFFLINE_ONLY',
              'core': {'path': str(source.relative_to(ROOT)), **core.metadata(source.read_bytes())},
              'image': {'path': PRODUCTION + 'Image', **core.metadata(image)},
              'image_manifest': {'path': PRODUCTION + 'manifest.json', **core.metadata(manifest_data)},
              'review_gate': {'path': GATE, **core.metadata(gate_data)},
              'actual_kernel_release': manifest['kernel_release'],
              'zero_byte_reviewed_files': zero_files,
              'passed': sum(case['passed'] for case in cases), 'total': len(cases), 'cases': cases,
              'board_tested': False, 'formal_flash_ready': False}
    core.write_new(output / 'result.json', core.json_bytes(result))
    print(json.dumps({'passed': result['passed'], 'total': result['total'],
                      'failed': [case for case in cases if not case['passed']]}, indent=2))
    raise SystemExit(0 if result['passed'] == result['total'] else 1)


if __name__ == '__main__':
    main()
