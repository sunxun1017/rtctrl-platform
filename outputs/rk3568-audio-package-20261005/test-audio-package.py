#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real byte/header/resource/overlay mutations; fixture is never deployable."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load():
    spec = importlib.util.spec_from_file_location('audio_package_tests', HERE / 'audio-package.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core


def rewrite_package(original, payloads):
    """Independent test writer updates sizes/ID, all component padding and 40 MiB tail."""
    header = bytearray(original[:2048])
    for name, offset in [('kernel', 8), ('ramdisk', 16), ('second', 24), ('dtb', 1648)]:
        struct.pack_into('<I', header, offset, len(payloads[name]))
    result = header
    image_id = hashlib.sha1()
    for name in ('kernel', 'ramdisk', 'second', 'dtb'):
        if name == 'dtb':
            image_id.update(struct.pack('<I', 0))
        blob = payloads[name]
        image_id.update(blob)
        image_id.update(struct.pack('<I', len(blob)))
        result.extend(blob)
        result.extend(bytes((-len(result)) % 2048))
    result[576:608] = image_id.digest() + bytes(12)
    assert len(result) <= 41943040
    result.extend(bytes(41943040 - len(result)))
    return bytes(result)


def reject(call, phrase=None):
    try:
        call()
    except (ValueError, OSError) as error:
        if phrase:
            assert phrase in str(error), str(error)
        return str(error)
    raise AssertionError('Invalid input accepted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    core = load()
    output = core.fresh_directory(args.out)
    cases = []

    def run(name, call):
        try:
            evidence = call()
            cases.append({'name': name, 'passed': True, 'evidence': evidence})
        except Exception as error:
            cases.append({'name': name, 'passed': False, 'error': type(error).__name__ + ': ' + str(error)})

    image = core.read_locked('outputs/rk3568-rcu-reset-20261004/Image', 34755072,
        'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457')
    inputs = {'kernel': image, 'mode': 'FIXTURE_ONLY_NOT_DEPLOYABLE',
              'fixture_source': {'path': 'outputs/rk3568-rcu-reset-20261004/Image', **core.metadata(image)},
              'production_Image_not_used': True}
    fixed = core.fixed_inputs()
    modules, _ = core.dependencies()
    original = modules['audit-boot.py'].inspect_boot(fixed['original'])
    sizes = {'kernel': len(image), 'ramdisk': 972203, 'second': 4591616, 'dtb': 163204}

    def changed_header(offset, value):
        result = bytearray(image)
        struct.pack_into('<Q', result, offset, value)
        return bytes(result)

    def dynamic_size():
        value = 35389440 + 2 * 1024 * 1024
        plan = core.image_plan(changed_header(16, value), original['header'], sizes)
        assert plan['image_header']['image_size'] == value
        assert plan['actual_plan']['kernel'] == [0x400000, 0x400000 + value]
        return plan['image_header']

    run('dynamic-effective-Image-size', dynamic_size)

    def gd_workspace():
        plan = core.image_plan(image, original['header'], sizes)
        assert plan['actual_plan']['fdt_workspace'] == [0xa100000, 0xa140000]
        assert plan['header_destination_overlaps']
        assert plan['header_addresses_are_actual_destinations'] is False
        assert plan['actual_destinations_verified'] is False
        assert plan['fresh_bank_and_reserved_ranges_verified'] is False
        return plan['actual_plan']

    run('gd-FDT-workspace-and-metadata-overlap-is-not-actual', gd_workspace)
    run('effective-memory-smaller-than-file', lambda: reject(
        lambda: core.image_plan(changed_header(16, len(image) - 1), original['header'], sizes), 'effective memory'))
    run('kernel-initrd-overlap', lambda: reject(
        lambda: core.image_plan(changed_header(16, 0x4000000), original['header'], sizes), 'intervals overlap'))
    run('effective-memory-overflow', lambda: reject(
        lambda: core.image_plan(changed_header(16, 0xffffffffffffffff), original['header'], sizes), 'effective memory'))
    run('text-offset-invalid-aligned-base', lambda: reject(
        lambda: core.image_plan(changed_header(8, 0x80000), original['header'], sizes), 'base alignment'))
    run('text-offset-valid-dynamic-2MiB', lambda: core.image_plan(changed_header(8, 0x200000), original['header'], sizes)['kernel_2m_aligned_base'])
    run('aligned-base-outside-usable-bank-rejected', lambda: reject(
        lambda: core.image_plan(changed_header(8, 0x400000), original['header'], sizes), 'aligned base outside'))
    run('BE-Image-rejected', lambda: reject(
        lambda: core.image_plan(changed_header(24, 11), original['header'], sizes), 'little-endian'))
    run('reserved-Image-flag-rejected', lambda: reject(
        lambda: core.image_plan(changed_header(24, 26), original['header'], sizes), 'flag bits'))
    run('wrong-page-size-flag-rejected', lambda: reject(
        lambda: core.image_plan(changed_header(24, 12), original['header'], sizes), '4 KiB'))
    run('4MiB-needs-any-base-flag', lambda: reject(
        lambda: core.image_plan(changed_header(24, 2), original['header'], sizes), 'any-physical-base'))
    run('empty-initrd-rejected', lambda: reject(
        lambda: core.image_plan(image, original['header'], {**sizes, 'ramdisk': 0}), 'Positive integer'))
    run('boolean-component-size-rejected', lambda: reject(
        lambda: core.image_plan(image, original['header'], {**sizes, 'ramdisk': True}), 'Positive integer'))
    run('negative-DT-component-size-rejected', lambda: reject(
        lambda: core.image_plan(image, original['header'], {**sizes, 'dtb': -1}), 'Positive integer'))
    run('FDT-workspace-capacity-rejected', lambda: reject(
        lambda: core.image_plan(image, original['header'], {**sizes, 'dtb': 0x40001}), 'workspace'))
    run('duplicate-manifest-key-rejected', lambda: reject(
        lambda: core.unique_json(b'{"image_sha256":"a","image_sha256":"b"}'), 'Duplicate JSON'))
    run('JSON-nonfinite-rejected', lambda: reject(lambda: core.unique_json(b'{"image_bytes":NaN}'), 'Non-finite'))
    run('escaped-repository-path-rejected', lambda: reject(lambda: core.relative_path('../third_party/x'), 'relative path'))
    run('absolute-repository-path-rejected', lambda: reject(lambda: core.relative_path('/tmp/x'), 'relative path'))
    image_manifest = {'image_bytes': len(image), 'image_sha256': core.metadata(image)['sha256'],
                      'image_crc32': core.metadata(image)['crc32'], 'text_offset': 0,
                      'image_memory_bytes': 35389440, 'kernel_release': '4.19.232'}
    run('pure-complete-Image-manifest-binding', lambda: core.validate_image_metadata(image_manifest, image))
    for key, value in [('image_bytes', len(image) - 1), ('image_sha256', '0' * 64),
                       ('image_crc32', '00000000'), ('text_offset', 1),
                       ('image_memory_bytes', 1), ('kernel_release', '4.19.231')]:
        run('Image-manifest-reject-' + key, lambda key=key, value=value: reject(
            lambda: core.validate_image_metadata({**image_manifest, key: value}, image)))
    run('Image-manifest-reject-bool-byte-size', lambda: reject(
        lambda: core.validate_image_metadata({**image_manifest, 'image_bytes': True}, image)))

    candidate = output / 'fixture-candidate'
    run('actual-AOSP-builder-fixture', lambda: core.construct_package(candidate, inputs)['status'])
    data = (candidate / 'boot-padded.img').read_bytes()
    report = core.inspect_candidate(data, inputs)
    payloads = {entry['name']: data[entry['offset']:entry['offset'] + entry['bytes']] for entry in report['components']}
    run('independent-frozen-directory-audit', lambda: core.audit_directory(candidate, inputs)['package'])
    run('nine-identical-pre-overlay-audio-DTs-and-two-original-logos', lambda: {
        'dtbs': report['resource']['dtb_count'], 'logos': report['resource']['logo_count'],
        'shim_sha256': report['components'][3]['sha256']})
    run('real-libfdt-five-properties-and-normal-mode', lambda: report['real_overlay'])
    run('builder-rejects-overwrite', lambda: reject(lambda: core.construct_package(candidate, inputs)))
    run('builder-rejects-outside-owned-output', lambda: reject(
        lambda: core.construct_package(ROOT / 'outputs/unowned-fixture', inputs), 'own build'))
    run('short-package-rejected', lambda: reject(lambda: core.inspect_candidate(data[:-1], inputs), '40 MiB'))
    run('long-package-rejected', lambda: reject(lambda: core.inspect_candidate(data + b'\0', inputs), '40 MiB'))

    def valid_format_policy_reject(name, mutant, phrase):
        format_report = modules['audit-boot.py'].inspect_boot(mutant, expected_concat_count=1)
        reason = reject(lambda: core.inspect_candidate(mutant, inputs), phrase)
        evidence = {'format_and_recomputed_ID_accepted': True, 'mutant': core.metadata(mutant), 'policy_rejection': reason}
        (output / (name + '.json')).write_text(json.dumps(evidence, indent=2) + '\n')
        assert format_report['package']['sha256'] == evidence['mutant']['sha256']
        return evidence

    kernel = bytearray(payloads['kernel'])
    kernel[1000] ^= 1
    run('kernel-content-recomputed-ID-policy-rejected', lambda: valid_format_policy_reject(
        'kernel-content-mutation', rewrite_package(data, {**payloads, 'kernel': bytes(kernel)}), 'Locked component policy: kernel'))
    run('ramdisk-content-recomputed-ID-policy-rejected', lambda: valid_format_policy_reject(
        'ramdisk-content-mutation', rewrite_package(data, {**payloads, 'ramdisk': b'X' + payloads['ramdisk'][1:]}), 'Locked component policy: ramdisk'))
    applied = core.read_locked(core.RUNTIME + 'build/audio-ram-shim-v1/applied-audit-only.dtb', *core.APPLIED)
    run('applied-audit-only-DT-recomputed-ID-policy-rejected', lambda: valid_format_policy_reject(
        'applied-DT-mutation', rewrite_package(data, {**payloads, 'dtb': applied}), 'Locked component policy: dtb'))

    def changed_resource(index, transform):
        resource = bytearray(payloads['second'])
        entry = report['resource']['entries'][index]
        blob = transform(resource[entry['offset']:entry['offset'] + entry['bytes']])
        assert len(blob) == entry['bytes']
        resource[entry['offset']:entry['offset'] + entry['bytes']] = blob
        table = (index + 1) * 512
        resource[table + 224:table + 244] = hashlib.sha1(blob).digest()
        return rewrite_package(data, {**payloads, 'second': bytes(resource)})

    logo_index = next(entry['index'] for entry in report['resource']['entries'] if entry['path'] == 'logo.bmp')
    run('logo-content-recomputed-resourceSHA-and-ID-policy-rejected', lambda: valid_format_policy_reject(
        'logo-content-mutation', changed_resource(logo_index, lambda blob: blob[:40] + bytes([blob[40] ^ 1]) + blob[41:]), 'RSCE content policy: logo.bmp'))
    dt_index = next(entry['index'] for entry in report['resource']['entries'] if entry['path'].endswith('.dtb'))
    real = modules['libfdt-v2.py'].RealLibFdt()
    opened = real.opened(fixed['dtb'])
    real.set_property(opened, '/chosen', 'phandle', struct.pack('>I', 0x2fb))
    changed_dt = real.packed(opened)
    assert len(changed_dt) == len(fixed['dtb'])
    run('RSCE-DT-phandle-recomputed-resourceSHA-and-ID-policy-rejected', lambda: valid_format_policy_reject(
        'resource-DT-mutation', changed_resource(dt_index, lambda blob: changed_dt), 'RSCE content policy'))
    resource = bytearray(payloads['second'])
    resource[512:1024], resource[1024:1536] = resource[1024:1536], resource[512:1024]
    run('RSCE-order-recomputed-ID-policy-rejected', lambda: valid_format_policy_reject(
        'resource-order-mutation', rewrite_package(data, {**payloads, 'second': bytes(resource)}), 'names/order'))
    shifted = bytearray(payloads['second'][:6144] + bytes(512) + payloads['second'][6144:])
    for entry in report['resource']['entries']:
        offset = 512 * (1 + entry['index']) + 260
        struct.pack_into('<I', shifted, offset, struct.unpack_from('<I', shifted, offset)[0] + 1)
    run('RSCE-noncanonical-offset-recomputed-ID-policy-rejected', lambda: valid_format_policy_reject(
        'resource-offset-mutation', rewrite_package(data, {**payloads, 'second': bytes(shifted)}), 'Canonical RSCE offset'))
    modified_header = bytearray(data)
    struct.pack_into('<I', modified_header, 12, 0x480000)
    run('header-metadata-policy-rejected-after-valid-ID', lambda: valid_format_policy_reject(
        'header-address-mutation', bytes(modified_header), 'header metadata policy: kernel_addr'))
    modified_cmd = bytearray(data)
    modified_cmd[64:576] = bytes(512)
    modified_cmd[64:64 + len(core.CMDLINE)] = core.CMDLINE.replace('panic=0', 'panic=1').encode()
    run('Linux-cmdline-policy-rejected-after-valid-ID', lambda: valid_format_policy_reject(
        'cmdline-mutation', bytes(modified_cmd), 'cmdline policy'))
    nonzero_tail = data[:-1] + b'X'
    run('nonzero-partition-tail-rejected', lambda: reject(lambda: core.inspect_candidate(nonzero_tail, inputs), 'partition tail'))
    bad_id = bytearray(data)
    bad_id[576] ^= 1
    run('incorrect-ID-rejected', lambda: reject(lambda: core.inspect_candidate(bytes(bad_id), inputs), 'ID SHA1'))

    link = output / 'symlink-input'
    link.symlink_to(candidate / 'boot-padded.img')
    run('symlink-input-rejected', lambda: reject(lambda: core.read_ordinary(link), 'Ordinary repository'))
    run('unreviewed-Image-provenance-rejected', lambda: reject(
        lambda: core.validate_review({}, {'accepted_for_offline_integration': False}, b'{}', image), 'Independent C3'))
    run('empty-source-map-rejected', lambda: reject(lambda: core.verify_hash_map({}), 'Nonempty'))
    run('abbreviated-SHA-rejected', lambda: reject(lambda: core.digest('12345678'), 'Full lowercase'))

    def production_cli_rejects_fixture():
        argv = [sys.executable, '-B', str(HERE / 'build-audio-package.py'), '--fixture',
                '--out', str(output / 'must-not-exist'), '--review-gate', 'missing.json']
        result = subprocess.run(argv, capture_output=True, timeout=30)
        (output / 'production-no-fixture.stdout').write_bytes(result.stdout)
        (output / 'production-no-fixture.stderr').write_bytes(result.stderr)
        assert result.returncode != 0 and b'unrecognized arguments: --fixture' in result.stderr
        assert not (output / 'must-not-exist').exists()
        return {'exit_code': result.returncode, 'rejected_unknown_fixture_switch': True}

    run('production-CLI-has-no-fixture-bypass', production_cli_rejects_fixture)
    # Check that a stale Image cannot become production through an argument override.
    argv = [sys.executable, '-B', str(HERE / 'build-audio-package.py'), '--image',
            'outputs/rk3568-rcu-reset-20261004/Image', '--out', str(output / 'must-not-exist'), '--review-gate', 'missing.json']
    def no_image_override():
        result = subprocess.run(argv, capture_output=True, timeout=30)
        (output / 'production-no-image-override.stdout').write_bytes(result.stdout)
        (output / 'production-no-image-override.stderr').write_bytes(result.stderr)
        assert result.returncode != 0 and b'unrecognized arguments: --image' in result.stderr
        assert not (output / 'must-not-exist').exists()
        return {'exit_code': result.returncode, 'rejected_image_override': True}
    run('production-CLI-has-no-Image-override', no_image_override)

    mutation_dir = output / 'manifest-mutation-fixture'
    shutil.copytree(candidate, mutation_dir)
    baseline_manifest = core.unique_json(core.read_ordinary(mutation_dir / 'manifest.json'))
    baseline_receipt = core.unique_json(core.read_ordinary(mutation_dir / 'receipt.json'))
    patches = [
        ('board-tested', {'board_tested': True}, 'offline-only boundary'),
        ('formal-flash-ready', {'formal_flash_ready': True}, 'offline-only boundary'),
        ('flash-authorized', {'flash_authorized': True}, 'offline-only boundary'),
        ('old-RCU-as-new-Image', {'native_pid1_old_rcu_image_check_is_new_image_identity': True}, 'old RCU check'),
        ('rootfs-cache-path', {'rootfs_board_path': '/cache/other'}, 'rootfs cache path'),
        ('wrong-rootfs-sha', {'inputs': {**baseline_manifest['inputs'],
                                       'rootfs': {**baseline_manifest['inputs']['rootfs'], 'sha256': '0' * 64}}}, 'fixed input binding'),
        ('wrong-official-commit', {'official_commit': '0' * 40}, 'official functions'),
        ('wrong-source-map', {'source_inputs': {}}, 'source snapshot metadata'),
    ]
    for name, patch, phrase in patches:
        def mutation_case(patch=patch, phrase=phrase):
            mutant = core.json_bytes({**baseline_manifest, **patch})
            (mutation_dir / 'manifest.json').write_bytes(mutant)
            receipt = {**baseline_receipt, 'files': {**baseline_receipt['files'], 'manifest.json': core.metadata(mutant)}}
            (mutation_dir / 'receipt.json').write_bytes(core.json_bytes(receipt))
            return {'rehash_of_self_consistent_inventory': True,
                    'reason': reject(lambda: core.audit_directory(mutation_dir, inputs), phrase)}
        run('rehash-manifest-policy-reject-' + name, mutation_case)

    def unexpected_inventory_file():
        (mutation_dir / 'not-in-freeze').write_bytes(b'fixture-only')
        return reject(lambda: core.audit_directory(mutation_dir, inputs), 'inventory set')
    run('extra-file-in-frozen-package-rejected', unexpected_inventory_file)

    result = {'mode': 'FIXTURE_ONLY_NOT_DEPLOYABLE', 'production_Image_not_used': True,
              'passed': sum(item['passed'] for item in cases), 'total': len(cases), 'cases': cases,
              'board_tested': False, 'formal_flash_ready': False,
              'test_source': core.metadata(Path(__file__).read_bytes()),
              'core_source': core.metadata((HERE / 'audio-package.py').read_bytes())}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'total': result['total'],
                      'failed': [case for case in cases if not case['passed']], 'production_Image_not_used': True}, indent=2))
    raise SystemExit(0 if result['passed'] == result['total'] else 1)


if __name__ == '__main__':
    main()
