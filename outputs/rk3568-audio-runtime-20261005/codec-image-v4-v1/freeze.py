#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read back the reviewed actual attempt and freeze only this owned directory."""
from pathlib import Path
import hashlib
import importlib.util
import json
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BUILDER_SHA = 'ac8e0fabbb5ee9dee12b136e576560c98e2efe9484727db1227338507a5c1fee'
BUILD_MANIFEST_SHA = '32241d1dfe9f2cbf17bae023065d87ee436173ba319a9f40b81ad5c7b1eb8e3c'
MODULE_SHA = 'aa594a46d660c929cdae71f81024659cf9f4beca032baf9a193ad6ded3476171'
PREFLIGHT_SHA = '3ba81b6c96c742637e0650ab61da468c194b9af49b960aa30fda39753cbf4f5b'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def load_builder():
    path = HERE / 'codec_builder.py'
    check(sha(path) == BUILDER_SHA, 'Reviewed builder changed')
    spec = importlib.util.spec_from_file_location('reviewed_codec_builder', path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.ordinary(path)
    return builder


def verify_actual(builder):
    out = HERE / 'build-v2'
    check(sha(builder.ordinary(out / 'manifest.json')) == BUILD_MANIFEST_SHA, 'Actual manifest changed')
    record = read(out / 'manifest.json')
    check(record['status'] == 'ACTUAL_COMPLETED_IMAGE_CODEC_ABI_VERIFIED' and record['build_exit_code'] == 0,
          'Actual build must have completed')
    check(sha(out / 'builder-snapshot.py') == BUILDER_SHA == record['builder_sha256'] ==
          record['audit_source_sha256'], 'Actual builder/audit identity changed')
    check(not any(record[key] for key in ['board_tested', 'loaded', 'unload_tested', 'deployed',
                                        'full_duplex_passed', 'accepted_for_board']), 'Offline scope changed')
    check(len(record['steps']) == 5 and [x['label'] for x in record['steps']] ==
          ['compiler-version', 'build', 'module-readelf', 'module-undefined', 'module-defined'], 'Step set changed')
    for item in record['steps']:
        check(item['exit'] == 0 and read(out / (item['label'] + '.command.json')) == item, 'Actual command status')
        for channel in ['stdout', 'stderr']:
            p = builder.ordinary(out / (item['label'] + '.' + channel))
            check(sha(p) == item[channel + '_sha256'], 'Actual log changed')
        check(not (out / (item['label'] + '.stderr')).read_bytes(), 'Actual stderr no longer empty')
    module = builder.ordinary(out / 'modules/snd-soc-rk817.ko')
    check(sha(module) == MODULE_SHA == record['module']['sha256'] and
          module.stat().st_size == 519072 == record['module']['bytes'], 'Actual module changed')
    check(record['actual_module'] == record['module'] and len(record['module']['imports']) == 32,
          'Actual import count/alias changed')
    data, sections = builder.elf_sections(module)
    check(sections == record['module']['sections'] and '__versions' not in sections and
          '.interp' not in sections and '.dynamic' not in sections, 'Actual ELF scope changed')
    metadata = {}
    sec = sections['.modinfo']
    for item in data[sec['offset']:sec['offset'] + sec['bytes']].split(b'\0'):
        if item:
            key, value = item.decode().split('=', 1)
            metadata.setdefault(key, []).append(value)
    check(metadata == record['module']['metadata'] and metadata['vermagic'] == [builder.VERMAGIC],
          'Actual module metadata changed')
    exports = builder.symbols(builder.ABI / 'Module.symvers')
    vmlinux = builder.symbols(builder.ABI / 'vmlinux.symvers')
    imports = {line.split()[-1] for line in (out / 'module-undefined.stdout').read_text().splitlines() if line.strip()}
    check(imports == set(record['module']['imports']), 'Actual undefined log differs')
    for name, item in record['module']['imports'].items():
        check(exports[name] == vmlinux[name] == item and item['provider'] == 'vmlinux' and not item['namespace'],
              'Actual import no longer closes: ' + name)
    command = builder.ordinary(out / 'modules/.rk817_codec.o.cmd')
    check(sha(command) == record['actual_primary_Kbuild_command_sha256'] and '-DMODULE' in command.read_text().splitlines()[0]
          and str(out / 'modules/rk817_codec.c') in command.read_text().splitlines()[0], 'Actual source command changed')
    check(sha(out / 'modules/rk817_codec.c') == builder.CODEC_SHA and
          sha(out / 'modules/rk817_codec.h') == builder.HEADER_SHA, 'Actual compiled translation input changed')
    check(not builder.symbols(out / 'modules/Module.symvers'), 'Module unexpectedly exports symbols')
    preflight = read(HERE / 'preflight-v6/result.json')
    check(sha(HERE / 'preflight-v6/result.json') == PREFLIGHT_SHA and
          preflight['helper_checks'] == len(preflight['steps']) == 30 and
          preflight['all_expected_helper_outcomes'] and not preflight['module_build_invoked'] and
          preflight['builder_sha256'] == BUILDER_SHA, 'Finite preflight evidence changed')
    check(read(HERE / 'build-v1/failure.json')['steps'] == [] and
          not (HERE / 'build-v1/manifest.json').exists(), 'Old failure was rewritten as success')
    return record


def verify_external(builder):
    actual = HERE / 'build-v2'
    before_source = read(actual / 'before-source-headers-scripts.json')
    current_source = builder.inventory(builder.SOURCE, builder.SOURCE_SELECTIONS, True)
    check(current_source == before_source == read(actual / 'after-source-headers-scripts.json'), 'Finite SOURCE changed')
    tracked = read(builder.IMAGE / 'integrated-source-inventory.json')
    builder.source_matches_image_inventory(current_source, tracked, builder.SOURCE_SELECTIONS)
    root_inventory = read(builder.ROOT_ABI / 'inventory.json')
    check(sha(builder.ROOT_ABI / 'inventory.json') == builder.ROOT_ABI_INVENTORY_SHA and
          sha(builder.ROOT_ABI / 'receipt.json') == builder.ROOT_ABI_RECEIPT_SHA, 'Root ABI identity changed')
    before_abi = read(actual / 'before-ABI.json')
    selected_abi = builder.inventory(builder.ABI, builder.COPY_DIRS + builder.COPY_FILES)
    check(selected_abi == before_abi == read(actual / 'after-ABI.json'), 'Current ABI changed')
    selected_root = builder.inventory(builder.ROOT_ABI / 'snapshot', builder.COPY_DIRS + builder.COPY_FILES)
    selected_shadow = builder.inventory(actual / 'kernel-abi', builder.COPY_DIRS + builder.COPY_FILES)
    check(selected_shadow == read(actual / 'after-shadow-ABI.json'), 'Private shadow changed')
    for value in [selected_abi, selected_root, selected_shadow]:
        builder.generated_matches_root_snapshot(value, root_inventory)
    check(selected_abi['regular_file_count'] == selected_root['regular_file_count'] ==
          selected_shadow['regular_file_count'] == 2020 and current_source['regular_file_count'] == 6360 and
          len(current_source['known_SDK_internal_links']) == 17, 'Accepted finite count changed')
    regular, links = {}, {}
    def add_regular(p, digest):
        p = builder.ordinary(p)
        check(sha(p) == digest, 'External ordinary SHA changed: ' + str(p))
        key = p.relative_to(ROOT).as_posix()
        item = {'sha256': digest, 'bytes': p.stat().st_size, 'mode': stat.S_IMODE(p.lstat().st_mode)}
        check(key not in regular or regular[key] == item, 'External duplicate identity conflict')
        if not p.is_relative_to(HERE):
            regular[key] = item
    for key, digest in read(actual / 'locks.json').items():
        add_regular(ROOT / key, digest)
    root_review = read(HERE / 'review-evidence-v1/input-manifest.json')
    check(root_review['root_originals_unchanged'] and not root_review['board_tested'] and
          not root_review['module_recompiled_during_snapshot'] and
          root_review['root_audit_receipt_sha256'] ==
          'bfbba6268dc8934a3b59585983c554f076cc7252dd5d62566fbc9216a148a518', 'Root audit snapshot scope changed')
    for key, item in root_review['inputs'].items():
        add_regular(ROOT / key, item['sha256'])
        original_input = builder.ordinary(ROOT / key)
        check(original_input.stat().st_size == item['bytes'] and
              stat.S_IMODE(original_input.lstat().st_mode) == item['mode'], 'Root audit original metadata changed')
        snapshot = builder.ordinary(HERE / 'review-evidence-v1' / item['snapshot'])
        check(sha(snapshot) == item['sha256'] and snapshot.stat().st_size == item['bytes'] and
              stat.S_IMODE(snapshot.lstat().st_mode) == item['mode'], 'Root audit copy changed')
    final_review = read(HERE / 'review-evidence-v2/input-manifest.json')
    check(final_review['root_original_unchanged'] and final_review['sha256'] ==
          '797e51e4f62190dc9c389d4a1624293c705b8c2bf78b5166fe0c01ddd55354db', 'Parent final note changed')
    add_regular(ROOT / final_review['source'], final_review['sha256'])
    for p in [ROOT / final_review['source'], HERE / 'review-evidence-v2' / final_review['snapshot']]:
        builder.ordinary(p)
        check(sha(p) == final_review['sha256'] and p.stat().st_size == final_review['bytes'] and
              stat.S_IMODE(p.lstat().st_mode) == final_review['mode'], 'Parent final note original/snapshot changed')
    for tree, selected in [(builder.SOURCE, current_source), (builder.ABI, selected_abi),
                           (builder.ROOT_ABI / 'snapshot', selected_root)]:
        for key, digest in selected['regular_files_sha256'].items():
            add_regular(tree / key, digest)
    for key, item in current_source['known_SDK_internal_links'].items():
        links[(builder.SOURCE / key).relative_to(ROOT).as_posix()] = item
    # The production typed helper also reads original SDK links/target directories.
    original = ROOT / 'third_party/linux-rk3588'
    for key in builder.DTC_DIRECTORY_LINKS:
        links[(original / key).relative_to(ROOT).as_posix()] = builder.inspect_DTC_prefix_link(original, key)
    return {'regular_files_metadata': regular, 'regular_file_count': len(regular),
            'typed_SDK_internal_links': links, 'typed_link_count': len(links),
            'actual_SOURCE_file_link_count': 4, 'actual_SOURCE_directory_link_count': 13,
            'original_SDK_directory_link_count': 13, 'ordinary_ancestors_checked': True,
            'link_targets_internal_and_kind_checked': True, 'directory_link_contents_traversed': False,
            'links_not_counted_as_regular_files': True, 'all_current_inputs_equal_reviewed_evidence': True}


def main():
    builder = load_builder()
    acceptance = read(builder.ordinary(HERE / 'review-acceptance-v1.json'))
    check(acceptance['root_authorized_freeze'] and acceptance['independent_readonly_actual_acceptance'] and
          acceptance['scope'] == 'actual_integration_v4_codec_offline_build_and_import_closure' and
          acceptance['build_manifest_sha256'] == BUILD_MANIFEST_SHA, 'Final limited acceptance required')
    record = verify_actual(builder)
    external = verify_external(builder)
    preflight = HERE / 'freeze-preflight-v1'
    builder.fresh(preflight)
    preflight.mkdir()
    write(preflight / 'external-inputs.json', external)
    files, metadata = {}, {}
    for p in sorted(HERE.rglob('*')):
        mode = p.lstat().st_mode
        if stat.S_ISDIR(mode):
            builder.ordinary_directory(p)
        else:
            builder.ordinary(p)
            name = p.relative_to(HERE).as_posix()
            files[name] = sha(p)
            metadata[name] = {'sha256': files[name], 'bytes': p.stat().st_size, 'mode': stat.S_IMODE(mode)}
    out = HERE / 'sealed-v1'
    builder.fresh(out)
    out.mkdir()
    manifest = {'schema': 'codec_image_v4_owned_ordinary_files_v1', 'files_sha256': files,
                'files_metadata': metadata, 'regular_file_count': len(files),
                'scope': acceptance['scope'], 'all_owned_ancestors_ordinary': True,
                'includes_original_failures_tools_full_shadow_objects_commands_and_module': True}
    write(out / 'file-manifest.json', manifest)
    sums = ''.join(digest + '  ' + name + '\n' for name, digest in files.items())
    sums += sha(out / 'file-manifest.json') + '  sealed-v1/file-manifest.json\n'
    (out / 'SHA256SUMS').write_text(sums)
    receipt = {'schema': 'actual_codec_image_v4_offline_seal_v1', 'scope': acceptance['scope'],
               'file_manifest_sha256': sha(out / 'file-manifest.json'), 'regular_file_count': len(files),
               'SHA256SUMS_sha256': sha(out / 'SHA256SUMS'),
               'external_inputs_manifest_sha256': sha(preflight / 'external-inputs.json'),
               'external_regular_file_count': external['regular_file_count'],
               'external_typed_link_count': external['typed_link_count'],
               'build_manifest_sha256': BUILD_MANIFEST_SHA, 'builder_sha256': BUILDER_SHA,
               'module_sha256': MODULE_SHA, 'module_bytes': 519072, 'actual_import_count': 32,
               'actual_step_count': 5, 'finite_helper_check_count': 30,
               'source_sha256': builder.CODEC_SHA, 'header_sha256': builder.HEADER_SHA,
               'image_sha256': record['image_sha256'], 'image_manifest_sha256': record['image_manifest_sha256'],
               'module_symvers_sha256': record['module_symvers_sha256'],
               'vmlinux_symvers_sha256': record['vmlinux_symvers_sha256'],
               'root_generated_ABI_inventory_sha256': builder.ROOT_ABI_INVENTORY_SHA,
               'root_generated_ABI_receipt_sha256': builder.ROOT_ABI_RECEIPT_SHA,
               'actual_source_regular_files': 6360, 'actual_SOURCE_file_links': 4,
               'actual_SOURCE_directory_links': 13, 'generated_ABI_regular_files': 2020,
               'review_acceptance_sha256': sha(HERE / 'review-acceptance-v1.json'),
               'root_fresh_audit_receipt_sha256':
               'bfbba6268dc8934a3b59585983c554f076cc7252dd5d62566fbc9216a148a518',
               'root_review_snapshot_manifest_sha256': sha(HERE / 'review-evidence-v1/input-manifest.json'),
               'parent_final_review_sha256':
               '797e51e4f62190dc9c389d4a1624293c705b8c2bf78b5166fe0c01ddd55354db',
               'parent_final_review_snapshot_manifest_sha256': sha(HERE / 'review-evidence-v2/input-manifest.json'),
               'generated_inventory_was_signed_at_Image_compile_time': False,
               'MODVERSIONS_enabled': False, 'CRC_runtime_enforcement_claimed': False,
               'board_tested': False, 'loaded': False, 'unload_tested': False, 'deployed': False,
               'accepted_for_board': False, 'full_duplex_passed': False,
               'limitations': ['Current generated ABI snapshot is after Image completion, before codec, not compile-time signing',
                               'Import closure and exact headers do not prove loading or unload safety',
                               'No control/PCM/DAPM/PLL/PM/voice/shared-DAI/hardware verification here']}
    write(out / 'receipt.json', receipt)
    for name, digest in files.items():
        p = builder.ordinary(HERE / name)
        check(sha(p) == digest and p.stat().st_size == metadata[name]['bytes'] and
              stat.S_IMODE(p.lstat().st_mode) == metadata[name]['mode'], 'Owned final readback changed')
    for line in (out / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        check(sha(builder.ordinary(HERE / name)) == digest, 'SUM final readback changed')
    check(sha(out / 'file-manifest.json') == receipt['file_manifest_sha256'] and
          sha(out / 'SHA256SUMS') == receipt['SHA256SUMS_sha256'], 'Seal self binding changed')
    live_owned = set()
    for p in HERE.rglob('*'):
        if stat.S_ISDIR(p.lstat().st_mode):
            builder.ordinary_directory(p)
        else:
            builder.ordinary(p)
            live_owned.add(p.relative_to(HERE).as_posix())
    check(live_owned == set(files) | {'sealed-v1/file-manifest.json', 'sealed-v1/SHA256SUMS',
                                     'sealed-v1/receipt.json'}, 'Complete owned live set changed')
    check(verify_external(builder) == external, 'External input set changed during freeze readback')
    print(json.dumps({'files': len(files), 'external_regular_files': external['regular_file_count'],
                      'external_typed_links': external['typed_link_count'], 'receipt_sha256': sha(out / 'receipt.json'),
                      'manifest_sha256': receipt['file_manifest_sha256'], 'SUM_sha256': receipt['SHA256SUMS_sha256'],
                      'accepted_for_board': False}))


if __name__ == '__main__':
    main()
