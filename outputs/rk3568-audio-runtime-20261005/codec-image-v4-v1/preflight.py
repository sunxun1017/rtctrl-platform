#!/usr/bin/env python3
"""Finite helper rejection checks; never compile or claim a completed v4 Image."""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import traceback

import codec_builder as builder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True, choices=['v6'])
    args = parser.parse_args()
    output = builder.HERE / ('preflight-' + args.version)
    builder.fresh(output)
    output.mkdir()
    steps = []
    (output / 'preflight-snapshot.py').write_bytes(Path(__file__).read_bytes())
    builder.write_json(output / 'invocation.json', {'argv': list(builder.os.sys.argv),
                         'module_build_invoked': False, 'live_v4_generated_ABI_read': True})

    def reject(name, call):
        try:
            call()
        except (ValueError, FileNotFoundError) as error:
            steps.append({'name': name, 'expected_rejection': True, 'error': str(error)})
        else:
            raise ValueError('Expected rejection missing: ' + name)

    try:
        # This synthetic dictionary only exercises the manifest validator.
        record = {'build_exit_code': 0, 'kernel_release': builder.RELEASE,
                  'config_sha256': builder.CONFIG_SHA, 'codec_source_sha256': builder.CODEC_SHA,
                  'source': builder.SOURCE.relative_to(builder.ROOT).as_posix(),
                  'build': builder.ABI.relative_to(builder.ROOT).as_posix(),
                  'compressed_audio_enabled': False, 'battery_algorithm_enabled': False,
                  'duplex_START_gates_relaxed': False}
        for key in ['image_sha256', 'module_symvers_sha256', 'vmlinux_symvers_sha256',
                    'integrated_source_inventory_sha256', 'builder_sha256']:
            record[key] = '1' * 64
        builder.validate_record(record)
        steps.append({'name': 'synthetic_complete_record_shape_only', 'accepted_parser_only': True})
        for name, key, value in [('failed_build', 'build_exit_code', 1),
                                 ('wrong_release', 'kernel_release', 'other'),
                                 ('wrong_config', 'config_sha256', '0' * 64),
                                 ('old_image_tree', 'source', '.deps/kernel-source/aiot-3568pq-audio-v3'),
                                 ('compressed_enabled', 'compressed_audio_enabled', True),
                                 ('duplex_gate_changed', 'duplex_START_gates_relaxed', True),
                                 ('missing_actual_symvers_sha', 'module_symvers_sha256', None)]:
            reject(name, lambda k=key, v=value: builder.validate_record({**record, k: v}))
        member = output / 'ordinary.fixture'
        member.write_text('fixture\n')
        builder.ordinary(member)
        steps.append({'name': 'ordinary_fixture_and_ancestry', 'accepted_parser_only': True})
        leaf = output / 'leaf-link'
        leaf.symlink_to(member.name)
        try:
            reject('symlink_leaf', lambda: builder.ordinary(leaf))
        finally:
            leaf.unlink()
        ancestor = output / 'ancestor-link'
        ancestor.symlink_to('.', target_is_directory=True)
        try:
            reject('symlink_ancestor', lambda: builder.ordinary(ancestor / member.name))
        finally:
            ancestor.unlink()
        bad = output / 'bad.symvers'
        for name, data in [('malformed_symvers', 'wrong record\n'),
                           ('duplicate_symvers', '0x00000000 a vmlinux EXPORT_SYMBOL\n0x00000000 a vmlinux EXPORT_SYMBOL\n')]:
            bad.write_text(data)
            reject(name, lambda: builder.symbols(bad))
            (output / (name + '.fixture')).write_text(data)
        valid = output / 'valid.symvers'
        valid.write_text('0x00000000 a vmlinux EXPORT_SYMBOL\n0x12345678 b vmlinux EXPORT_SYMBOL_GPL NS\n')
        parsed = builder.symbols(valid)
        builder.require(len(parsed) == 2 and parsed['b']['namespace'] == 'NS', 'Symvers parser failed')
        steps.append({'name': 'symvers_namespace_preserved_for_later_import_rejection', 'accepted_parser_only': True})
        binary = output / 'invalid.elf'
        for name, data in [('empty_ELF', b''), ('non_ELF', b'0' * 64)]:
            binary.write_bytes(data)
            reject(name, lambda: builder.elf_sections(binary))
        # Deliberately invalid synthetic ET_REL: wrong architecture, no sections.
        data = bytearray(64)
        data[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<HHIQQQIHHHHHH', data, 16, 1, 62, 1, 0, 0, 0, 0, 64, 0, 0, 64, 0, 0)
        binary.write_bytes(data)
        reject('wrong_architecture_ELF', lambda: builder.elf_sections(binary))
        expected_names = {'synthetic_complete_record_shape_only', 'failed_build', 'wrong_release', 'wrong_config',
                          'old_image_tree', 'compressed_enabled', 'duplex_gate_changed', 'missing_actual_symvers_sha',
                          'ordinary_fixture_and_ancestry', 'symlink_leaf', 'symlink_ancestor', 'malformed_symvers',
                          'duplicate_symvers', 'symvers_namespace_preserved_for_later_import_rejection',
                          'empty_ELF', 'non_ELF', 'wrong_architecture_ELF'}
        builder.require(len(steps) == 17 and {item['name'] for item in steps} == expected_names, 'Original preflight coverage changed')
        image_record = json.loads(builder.ordinary(builder.IMAGE / 'manifest.json').read_text())
        builder.require(builder.sha(builder.IMAGE / 'manifest.json') ==
                        '8df525843cac41fd0e272351bc41d0e573c25570cfed7e60f1990b9fe97aa33a', 'Actual completed Image changed')
        tracked_path = builder.ordinary(builder.IMAGE / 'integrated-source-inventory.json')
        builder.require(builder.sha(tracked_path) == image_record['integrated_source_inventory_sha256'], 'Actual Image source inventory changed')
        tracked = json.loads(tracked_path.read_text())
        full_finite_source = builder.inventory(builder.SOURCE, builder.SOURCE_SELECTIONS, True)
        builder.source_matches_image_inventory(full_finite_source, tracked, builder.SOURCE_SELECTIONS)
        steps.append({'name': 'actual_full_finite_SOURCE_keys_and_17_SDK_links_match_Image', 'accepted_parser_only': True})
        for kind in ['positive', 'wrong_kind', 'wrong_text', 'missing_target', 'unknown']:
            typed_tree = output / ('typed-link-' + kind)
            name = 'scripts/dtc/include-prefixes/' + ('unknown' if kind == 'unknown' else 'arc')
            link = typed_tree / name
            link.parent.mkdir(parents=True)
            target = typed_tree / 'arch/arc/boot/dts'
            if kind == 'wrong_kind':
                target.parent.mkdir(parents=True)
                target.write_text('file target fixture\n')
            elif kind not in ['missing_target', 'unknown']:
                target.mkdir(parents=True)
            link.symlink_to('../../../arch/other/boot/dts' if kind == 'wrong_text' else '../../../arch/arc/boot/dts')
            try:
                if kind == 'positive':
                    item = builder.inspect_DTC_prefix_link(typed_tree, name)
                    builder.require(item['target_kind'] == 'ordinary_directory' and not item['target_contents_traversed'], 'Typed positive failed')
                    steps.append({'name': 'typed_DTC_directory_positive', 'accepted_parser_only': True})
                else:
                    reject('typed_DTC_' + kind + '_rejected', lambda: builder.inspect_DTC_prefix_link(typed_tree, name))
            finally:
                link.unlink()
        fixture = output / 'source-fixture'
        header = fixture / 'include/sound/soc.h'
        header.parent.mkdir(parents=True)
        shutil.copy2(builder.ordinary(builder.SOURCE / 'include/sound/soc.h'), header)
        original = builder.inventory(fixture, ['include/sound/soc.h'])
        builder.source_matches_image_inventory(original, tracked, ['include/sound/soc.h'])
        steps.append({'name': 'actual_Image_selected_header_positive_identity', 'accepted_parser_only': True})
        # Mutate only an owned header copy. Actual SOURCE/BUILD remain untouched.
        with header.open('ab') as stream:
            stream.write(b'\n/* owned finite drift fixture after Image completion */\n')
        altered = builder.inventory(fixture, ['include/sound/soc.h'])
        old_path = builder.HERE / 'builder-evidence-v1/codec_builder.py'
        builder.require(builder.sha(old_path) == '1db4beeb676abc95374d74d6ecce0f59f91d6513ee3ed676cef1d6912b4c7d5f', 'Old rejected builder changed')
        old = old_path.read_text()
        call = next(node for node in ast.walk(ast.parse(old)) if isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and node.func.id == 'require' and len(node.args) == 2 and
                    isinstance(node.args[1], ast.Constant) and node.args[1].value == 'Original Image generated ABI/source changed')
        expression = ast.Expression(body=call.args[0])
        old_accepts_drift = eval(compile(ast.fix_missing_locations(expression), str(old_path), 'eval'),
                                 {'before_abi': {}, 'after_abi': {}, 'before_source': altered, 'after_source': altered})
        builder.require(old_accepts_drift, 'Original real before/after guard red fixture did not reproduce')
        old_fragment = ast.get_source_segment(old, call)
        reject('completed_Image_header_drift_rejected', lambda: builder.source_matches_image_inventory(altered, tracked, ['include/sound/soc.h']))
        missing = copy.deepcopy(original)
        missing['regular_files_metadata'].clear()
        missing['regular_files_sha256'].clear()
        reject('completed_Image_missing_source_entry_rejected', lambda: builder.source_matches_image_inventory(missing, tracked, ['include/sound/soc.h']))
        extra = copy.deepcopy(original)
        extra['regular_files_metadata']['include/sound/untracked-fixture.h'] = original['regular_files_metadata']['include/sound/soc.h']
        extra['regular_files_sha256']['include/sound/untracked-fixture.h'] = original['regular_files_sha256']['include/sound/soc.h']
        reject('completed_Image_extra_source_entry_rejected', lambda: builder.source_matches_image_inventory(extra, tracked, ['include/sound/soc.h']))
        builder.require(builder.sha(builder.ROOT_ABI / 'receipt.json') == builder.ROOT_ABI_RECEIPT_SHA and
                        builder.sha(builder.ROOT_ABI / 'inventory.json') == builder.ROOT_ABI_INVENTORY_SHA, 'Root snapshot changed')
        root_inventory = json.loads((builder.ROOT_ABI / 'inventory.json').read_text())
        actual_abi = builder.inventory(builder.ABI, builder.COPY_DIRS + builder.COPY_FILES)
        builder.generated_matches_root_snapshot(actual_abi, root_inventory)
        steps.append({'name': 'actual_current_generated_ABI_matches_root_snapshot', 'accepted_parser_only': True})
        altered_abi = copy.deepcopy(actual_abi)
        altered_abi['regular_files_metadata']['include/generated/autoconf.h']['sha256'] = '0' * 64
        reject('root_generated_snapshot_drift_rejected', lambda: builder.generated_matches_root_snapshot(altered_abi, root_inventory))
        builder.require(builder.sha(builder.HERE / 'prepared-inputs-v1.json') == builder.PREPARED_INPUTS_SHA, 'Prepared manifest changed')
        mandatory = {builder.HERE / 'source-v1/rk817_codec.c': builder.CODEC_SHA}
        reject('conflicting_mandatory_codec_lock_rejected', lambda: builder.insert_lock(mandatory,
               builder.HERE / 'source-v1/rk817_codec.c', '0' * 64))
        builder.require(mandatory[builder.HERE / 'source-v1/rk817_codec.c'] == builder.CODEC_SHA, 'Conflicting lock changed mandatory value')
        builder.require(len(steps) == 30, 'New finite preflight total changed')
        result = {'helper_checks': len(steps), 'steps': steps, 'all_expected_helper_outcomes': True,
                  'builder_sha256': builder.sha(builder.HERE / 'codec_builder.py'),
                  'preflight_sha256': builder.sha(Path(__file__)), 'prepared_inputs_sha256': builder.sha(builder.HERE / 'prepared-inputs-v1.json'),
                  'synthetic_fixtures_not_real_Image_or_module': True, 'module_build_invoked': False,
                  'live_v4_generated_ABI_read': True, 'Image_v4_completion_asserted': True,
                  'old_before_after_guard_actual_fragment': old_fragment,
                  'old_before_after_guard_fragment_sha256': hashlib.sha256(old_fragment.encode()).hexdigest(),
                  'old_guard_business_reds': 1, 'new_same_source_drift_rejection_passed': True,
                  'old_fixture_scope': 'Only the exact production before/after guard expression, not old full builder or module Kbuild',
                  'new_fixture_scope': 'Real new production identity helpers; physical owned header drift and synthetic ABI metadata drift',
                  'actual_Image_manifest_sha256': builder.sha(builder.IMAGE / 'manifest.json'),
                  'actual_Image_source_inventory_sha256': builder.sha(tracked_path),
                  'root_generated_inventory_sha256': builder.ROOT_ABI_INVENTORY_SHA,
                  'actual_finite_source_regular_files': full_finite_source['regular_file_count'],
                  'actual_known_SDK_file_links': 4, 'actual_known_SDK_directory_links': 13,
                  'actual_module_ABI_verified': False, 'board_tested': False}
        builder.write_json(output / 'result.json', result)
        print(json.dumps({'helper_checks': len(steps), 'all_expected_outcomes': True, 'module_build_invoked': False}))
    except Exception:
        (output / 'failure.traceback').write_text(traceback.format_exc())
        builder.write_json(output / 'failure.json', {'steps': steps, 'module_build_invoked': False, 'ABI_verified': False})
        raise


if __name__ == '__main__':
    main()
