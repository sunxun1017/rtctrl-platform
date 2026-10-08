#!/usr/bin/env python3
"""Real new Image/codec/runtime closure and bounded identity rejection checks."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GATE = 'outputs/rk3568-audio-runtime-20261005/build/review-gate-v3.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('production_v3', HERE / 'audio-package-v3.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    output = core.fresh_directory(args.out)
    inputs = core.production_inputs(GATE)
    manifest_data = core.read_ordinary(core.relative_path(core.PRODUCTION + 'manifest.json'))
    manifest = core.unique_json(manifest_data)
    gate_data = core.read_ordinary(core.relative_path(GATE))
    gate = core.unique_json(gate_data)
    codec_data = core.read_ordinary(core.relative_path(core.RUNTIME + 'build/integrated-codec-v2/manifest.json'))
    codec = core.unique_json(codec_data)
    cases = []

    def test(name, call):
        try:
            value = call()
            cases.append({'name': name, 'passed': True, 'evidence': value})
        except Exception as error:
            cases.append({'name': name, 'passed': False, 'error': type(error).__name__ + ': ' + str(error)})

    def reject(call, phrase):
        try:
            call()
        except (ValueError, OSError) as error:
            assert phrase in str(error), str(error)
            return str(error)
        raise AssertionError('Invalid input accepted')

    test('actual-complete-production-closure', lambda: {'Image': core.metadata(inputs['kernel']),
         'runtime': inputs['runtime'], 'reviewed_files': len(inputs['provenance']['reviewed_files_sha256'])})
    for key, value in [('cpu_source_sha256', '0' * 64), ('cpu_v11_inventory_sha256', '0' * 64),
                       ('cpu_v10_manifest_sha256', '0' * 64), ('battery_algorithm_enabled', True)]:
        test('new-Image-' + key + '-rejected', lambda key=key, value=value: reject(
            lambda: core.validate_review({**manifest, key: value}, gate, gate_data, inputs['kernel']),
            'Image source/config/CPU binding'))
    test('unreviewed-v11-gate-rejected', lambda: reject(
        lambda: core.validate_review(manifest, {**gate, 'cpu_v11_independent_review_completed': False}, gate_data, inputs['kernel']),
        'Independent C3/CPU v11'))
    test('Image-without-v11-delta-rejected', lambda: reject(
        lambda: core.validate_review({**manifest, 'patches_sha256': {name: value for name, value in manifest['patches_sha256'].items()
                                     if not name.endswith('/delta-v10-v11.patch')}}, gate, gate_data, inputs['kernel']), 'exact patch series'))
    module = inputs['runtime_blobs']['snd-soc-rk817.ko']

    def codec_check(record, binary=module):
        return core.validate_codec(record, binary, inputs['kernel'], manifest_data, manifest)

    for key in ('image_sha256', 'image_manifest_sha256'):
        test('codec-' + key + '-wrong-rejected', lambda key=key: reject(
            lambda: codec_check({**codec, key: '0' * 64}), 'Codec exact new Image binding'))
    for key, value in [('source_sha256', '0' * 64), ('header_sha256', '0' * 64),
                       ('module_symvers_sha256', '0' * 64), ('abi_unchanged', False)]:
        test('codec-' + key + '-wrong-rejected', lambda key=key, value=value: reject(
            lambda: codec_check({**codec, key: value}), 'Codec source/ABI binding'))
    damaged = bytearray(module)
    damaged[-1] ^= 1
    test('codec-one-byte-change-rejected', lambda: reject(lambda: codec_check(codec, bytes(damaged)), 'complete content binding'))
    wrong_vermagic = copy.deepcopy(codec)
    wrong_vermagic['module']['metadata']['vermagic'] = ['wrong']
    test('codec-wrong-vermagic-rejected', lambda: reject(lambda: codec_check(wrong_vermagic), 'exact vermagic'))
    wrong_import = copy.deepcopy(codec)
    first_import = next(iter(wrong_import['module']['imports']))
    wrong_import['module']['imports'][first_import]['crc'] = '0xffffffff'
    test('codec-wrong-import-ABI-rejected', lambda: reject(lambda: codec_check(wrong_import), 'actual new Image imports'))
    missing_headers = copy.deepcopy(codec)
    missing_headers['abi_inventory'] = {name: value for name, value in codec['abi_inventory'].items()
                                        if name in ('.config', 'Module.symvers', 'vmlinux.symvers')}
    test('codec-missing-generated-headers-rejected', lambda: reject(
        lambda: codec_check(missing_headers), 'exact ordinary file set'))
    missing_import = copy.deepcopy(codec)
    del missing_import['module']['imports'][next(iter(missing_import['module']['imports']))]
    test('codec-missing-real-ELF-import-rejected', lambda: reject(
        lambda: codec_check(missing_import), 'actual complete ELF audit binding'))
    test('actual-production-directory-audit', lambda: core.audit_directory(HERE / 'build/ram-audio-v3', inputs)['package'])
    test('old-v2-production-package-rejected', lambda: reject(
        lambda: core.audit_directory(HERE / 'build/ram-audio-v2', inputs), 'Locked component policy: kernel'))
    empty = output / 'empty-input'
    core.write_new(empty, b'')
    test('zero-byte-reviewed-log-still-readable', lambda: core.metadata(core.read_ordinary(empty)))
    test('empty-JSON-still-rejected', lambda: reject(lambda: core.unique_json(core.read_ordinary(empty)), 'Expecting value'))
    test('empty-Image-still-rejected', lambda: reject(
        lambda: core.validate_image_metadata(manifest, b''), 'Complete Image content binding'))
    result = {'mode': 'REAL_PRODUCTION_INPUT_REGRESSION_OFFLINE_ONLY',
              'core_source': core.metadata((HERE / 'audio-package-v3.py').read_bytes()),
              'test_source': core.metadata(Path(__file__).read_bytes()),
              'Image_manifest': core.metadata(manifest_data), 'review_gate': core.metadata(gate_data),
              'codec_manifest': core.metadata(codec_data), 'passed': sum(case['passed'] for case in cases),
              'total': len(cases), 'cases': cases, 'board_tested': False, 'physical_sound_verified': False,
              'formal_flash_ready': False, 'production_Image_faked': False}
    core.write_new(output / 'result.json', core.json_bytes(result))
    print(json.dumps({'passed': result['passed'], 'total': result['total'], 'failed': [c for c in cases if not c['passed']]}, indent=2))
    raise SystemExit(0 if result['passed'] == result['total'] else 1)


if __name__ == '__main__':
    main()
