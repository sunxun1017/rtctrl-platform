#!/usr/bin/env python3
"""Pure address/metadata rejection models. Never construct a production Image."""
import argparse
import importlib.util
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    output = HERE / 'build' / args.out
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('policy_v3', HERE / 'audio-package-v3.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
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
        except ValueError as error:
            assert phrase in str(error), str(error)
            return str(error)
        raise AssertionError('Invalid input accepted')

    image = bytearray(64)
    image[56:60] = b'ARM\x64'
    struct.pack_into('<QQQ', image, 8, 0, 35389440, 10)
    image = bytes(image)
    header = {'kernel_addr': 0x80008000, 'ramdisk_addr': 0x84000000,
              'second_addr': 0x80f00000, 'dtb_addr': 0x83000000}
    sizes = {'kernel': len(image), 'ramdisk': 972203, 'second': 6000000, 'dtb': 163204}

    def mutation(offset, fmt, value):
        changed = bytearray(image)
        struct.pack_into(fmt, changed, offset, value)
        return bytes(changed)

    test('labeled-fixture-static-address-plan', lambda: core.image_plan(image, header, sizes))
    test('kernel-vs-initrd-overlap-rejected', lambda: reject(
        lambda: core.image_plan(mutation(16, '<Q', 0x04000001), header, sizes), 'intervals overlap'))
    test('initrd-in-memory-bank-hole-rejected', lambda: reject(
        lambda: core.image_plan(image, header, {**sizes, 'ramdisk': 0x4400001}), 'historical bank constraints'))
    test('ramdisk-overlaps-FDT-rejected', lambda: reject(
        lambda: core.image_plan(image, header, {**sizes, 'ramdisk': 0x7000000}), 'intervals overlap'))
    for name, offset, fmt, value, phrase in [
        ('too-small-image-size', 16, '<Q', 63, 'bounded effective memory size'),
        ('overflow-image-size', 16, '<Q', 0xffffffffffffffff, 'bounded effective memory size'),
        ('invalid-endianness', 24, '<Q', 11, 'little-endian'),
        ('unknown-flags', 24, '<Q', 0x1a, 'defined flag'),
        ('wrong-page-size', 24, '<Q', 12, '4 KiB'),
        ('placement-flag-absent', 24, '<Q', 2, 'placement flag'),
        ('wrong-text-offset', 8, '<Q', 1, 'base alignment'),
        ('reserved-nonzero', 32, '<Q', 1, 'reserved header'),
    ]:
        test(name, lambda offset=offset, fmt=fmt, value=value, phrase=phrase: reject(
            lambda: core.image_plan(mutation(offset, fmt, value), header, sizes), phrase))
    test('oversized-DT-workspace-rejected', lambda: reject(
        lambda: core.image_plan(image, header, {**sizes, 'dtb': 0x40001}), 'FDT blob exceeds'))
    test('boolean-component-size-rejected', lambda: reject(
        lambda: core.image_plan(image, header, {**sizes, 'dtb': True}), 'integer component sizes'))
    test('missing-component-rejected', lambda: reject(
        lambda: core.image_plan(image, header, {k: v for k, v in sizes.items() if k != 'dtb'}), 'component sizes'))
    manifest = {**{'image_' + k: v for k, v in core.metadata(image).items()},
                'text_offset': 0, 'image_memory_bytes': 35389440,
                'kernel_release': '5.10.160-rt89-g9f9e9d18574d-dirty'}
    test('labeled-fixture-Image-metadata', lambda: core.validate_image_metadata(manifest, image))
    for key, value, phrase in [('image_bytes', 65, 'content binding'), ('image_sha256', '0' * 64, 'content binding'),
                               ('image_crc32', '00000000', 'content binding'), ('text_offset', 1, 'header binding'),
                               ('image_memory_bytes', True, 'header binding'), ('kernel_release', '4.19.232', 'kernel release')]:
        test('Image-' + key + '-wrong-rejected', lambda key=key, value=value, phrase=phrase: reject(
            lambda: core.validate_image_metadata({**manifest, key: value}, image), phrase))
    test('codec-old-Image-rejected-before-ABI', lambda: reject(
        lambda: core.validate_codec({'image_sha256': '0' * 64}, b'', image, b'{}', manifest), 'exact new Image binding'))
    test('codec-wrong-manifest-rejected-before-ABI', lambda: reject(
        lambda: core.validate_codec({'image_sha256': core.metadata(image)['sha256'], 'image_manifest_sha256': '0' * 64},
                                   b'', image, b'{}', manifest), 'exact new Image binding'))
    test('codec-wrong-source-rejected-before-ABI', lambda: reject(
        lambda: core.validate_codec({'image_sha256': core.metadata(image)['sha256'],
                                    'image_manifest_sha256': core.metadata(b'{}')['sha256']},
                                   b'', image, b'{}', {**manifest, 'module_symvers_sha256': '0' * 64}), 'source/ABI binding'))
    result = {'mode': 'FIXTURE_ONLY_NOT_DEPLOYABLE', 'production_Image_faked': False,
              'core_source': core.metadata((HERE / 'audio-package-v3.py').read_bytes()),
              'test_source': core.metadata(Path(__file__).read_bytes()),
              'passed': sum(case['passed'] for case in cases), 'total': len(cases), 'cases': cases,
              'board_tested': False, 'formal_flash_ready': False}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'total': result['total'], 'failed': [c for c in cases if not c['passed']]}, indent=2))
    raise SystemExit(0 if result['passed'] == result['total'] else 1)


if __name__ == '__main__':
    main()
