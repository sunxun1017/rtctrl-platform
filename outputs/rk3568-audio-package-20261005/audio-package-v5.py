#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""SHA-bound offline audio RAM package policy. No device or flashing operations."""
from contextlib import ExitStack
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
from types import ModuleType, SimpleNamespace
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = 'outputs/rk3568-boot-package-20261005/'
RUNTIME = 'outputs/rk3568-audio-runtime-20261005/'
PRODUCTION = RUNTIME + 'build/integration-v4/'
CMDLINE = 'console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init ro loglevel=7 panic=0'
SIZE = 40 * 1024 * 1024
COMMIT = '9f9e9d18574d0914c0d192a90c3babfe1fd63c95'
CONFIG = '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'
CPU_MANIFEST = '7ea40e4a346c32240ea7c903c400de7d68ab56c2b96f12f807d496c5099327be'
# v5 retains v4 mechanics; binds public14/privateASoC1, actual codec-v4 ABI and no-START peer.
CPU_V10_MANIFEST = '92344de6c38aeb3353134150ec9bca75fad84dc3d2071e1bbd7d611fd0d73b56'
CPU_SOURCE = '7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141'
CPU_INVENTORY = '46b7d7851a135de4943303ea62ae3c6abe5e207d3f1390f4a4c5b333f7b5e8c8'
CPU_DELTA = '64957ca517417c02dbb7c2a52306bb3020f5b2b730cdf636a0f60fbd950a078c'
CPU_FILES = {
    RUNTIME + 'cpu-lifecycle-v12/source/manifest.json': CPU_MANIFEST,
    RUNTIME + 'cpu-lifecycle-v12/source/sound/soc/rockchip/rockchip_i2s_tdm.c': CPU_SOURCE,
    RUNTIME + 'cpu-lifecycle-v12/frozen-output-manifest.json': CPU_INVENTORY,
}
CPU_ADDENDUM_INVENTORY = 'b0f9e8516ff927a4025c459dc15288ec294db301c6f313dc27bf8594f0c954ed'
CPU_ADDENDUM_RECEIPT = '8033e8f367367d9c921ab8c255b3f6793cddb56e5d623e3e9519ea15425a5f2f'
CPU_PRIOR_SOURCE = '87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c'
CPU_PRIOR_DELTA = 'dd31e7208c71bdc7dac8b41c8d82f9e2702f77c743a80214044d8b28e5422437'
REVIEW_GATE_SHA = 'b5a3de60be520d78b4f48a5bfcf6971b81241385e22e8fe5913336d9ecf580c4'
CPU_ROOT_HELPER = '91ecd2f28584cc46da99e5414d020b52bdfabca20b88e29d164db3727e9111c6'


def validate_cpu_run(kind, result, invocation):
    """Finite root reexecution schema, separate from author saved outputs."""
    total = {'red': 5, 'format': 90, 'sysclk': 48, 'params': 140}[kind]
    red = kind == 'red'
    require(result.get('source_sha256') == (CPU_PRIOR_SOURCE if red else CPU_SOURCE) and
            result.get('expected_red') is red and result.get('model_only') is True and
            result.get('board_tested') is False, 'Root CPU model source/boundary')
    require(invocation.get('kind') == kind and type(invocation.get('exit')) is int and invocation['exit'] == 0 and
            invocation.get('fresh_execution_requested') is True and invocation.get('runner_completed_all_environments') is True and
            invocation.get('helper_sha256') == CPU_ROOT_HELPER and invocation.get('frozen_inventory_sha256') == CPU_INVENTORY and
            invocation.get('frozen_files_verified') == 2287 and invocation.get('board_tested') is False,
            'Root CPU fresh execution invocation')
    require(set(result.get('runs', {})) == {'host', 'asan-ubsan', 'aarch64-qemu'}, 'Root CPU three environments')
    expected_failure = ['worker_before_fmt_out_reaches_idle'] if red else []
    for label, run in result['runs'].items():
        require(run.get('tests') == {'total': total, 'passed': total - int(red)} and
                type(run.get('exit')) is int and run['exit'] == int(red) and run.get('failures') == expected_failure,
                'Root CPU complete model results')
        require(run.get('expected_red_reproduced') is red, 'Root CPU expected red reproduced')
    return total


def cpu_v12_proofs(gate):
    bound = gate['files_sha256']
    require(gate.get('cpu_v12_actual_candidate_ABI_files') == 2020, 'CPU v12 actual candidate ABI count correction')
    declared = gate.get('cpu_v12_root_fresh_execution')
    require(isinstance(declared, dict) and set(declared) == {'red', 'format', 'sysclk', 'params'}, 'Root CPU four fresh suites')
    initial = checked_inventory(RUNTIME + 'cpu-lifecycle-v12', CPU_INVENTORY)
    addendum = checked_inventory(RUNTIME + 'cpu-lifecycle-v12/post-freeze-review-v1', CPU_ADDENDUM_INVENTORY)
    correction_name = RUNTIME + 'cpu-lifecycle-v12/post-freeze-review-v1/receipt.json'
    correction_data = read_ordinary(relative_path(correction_name))
    require(bound.get(correction_name) == metadata(correction_data)['sha256'] == CPU_ADDENDUM_RECEIPT,
            'CPU v12 ABI correction receipt binding')
    correction = unique_json(correction_data)
    require(correction.get('actual_v2_ABI_files') == 2020 and
            correction.get('production_source_and_initial_freeze_unchanged') is True and
            correction.get('initial_inventory_sha256') == CPU_INVENTORY, 'CPU v12 ABI correction semantics')
    suites = {}
    for kind in ['red', 'format', 'sysclk', 'params']:
        directory = RUNTIME + 'build/root-v12-' + kind + '-v1'
        data = {}
        for filename in ['result.json', 'root-invocation.json']:
            name = directory + '/' + filename
            blob = read_ordinary(relative_path(name))
            require(bound.get(name) == metadata(blob)['sha256'], 'Root CPU fresh receipt review binding')
            data[filename] = blob
        result, invocation = (unique_json(data[name]) for name in ['result.json', 'root-invocation.json'])
        total = validate_cpu_run(kind, result, invocation)
        require(declared[kind] == {'tests_per_environment': total, 'passed_per_environment': total - int(kind == 'red'),
                                  'result_sha256': metadata(data['result.json'])['sha256'], 'fresh_compilation': True},
                'Root CPU fresh gate summary binding')
        for label, run in result['runs'].items():
            binary = ('format-pm-' if kind in ['red', 'format'] else 'sysclk-') + label
            for filename, key in [(binary, 'binary_sha256'), (label + '.stdout', 'stdout_sha256'), (label + '.stderr', 'stderr_sha256')]:
                blob = read_ordinary(relative_path(directory + '/' + filename))
                require(metadata(blob)['sha256'] == digest(run[key]), 'Root CPU fresh executed artifact binding')
        for filename, key in [('root-invocation.stdout', 'stdout_sha256'), ('root-invocation.stderr', 'stderr_sha256')]:
            blob = read_ordinary(relative_path(directory + '/' + filename))
            require(metadata(blob)['sha256'] == digest(invocation[key]), 'Root CPU invocation output binding')
        suites[kind] = {'directory': directory, 'result': metadata(data['result.json']),
                        'invocation': metadata(data['root-invocation.json']), 'tests_per_environment': total,
                        'passed_per_environment': total - int(kind == 'red')}
    note_name = RUNTIME + 'REVIEW-CPU-v12-20261006.md'
    note = read_ordinary(relative_path(note_name))
    require(metadata(note)['sha256'] == bound.get(note_name), 'CPU v12 final independent review note binding')
    return {'initial_inventory': initial, 'correction_inventory': addendum,
            'correction_receipt': {'path': correction_name, **metadata(correction_data)},
            'actual_candidate_ABI_files': 2020, 'root_fresh_suites': suites,
            'final_independent_review': {'path': note_name, **metadata(note)},
            'board_tested': False, 'initial_idle_verified_on_board': False}


RUNTIME_FIXED = {
    'audio-session-guard': (RUNTIME + 'session-guard-v4/build/audio-session-guard', 741560,
                            '8740384398313be87a13245e854d6fc5a17a10f3794bdd83966e933c894c6f69'),
    'alsa-inspect': ('outputs/rk3568-audio-20261005/build/inspect-v4/alsa-inspect', 650408,
                     '118cf99482cdd65acdfae8c5e85530a76bf60c90b0b0498e8f285223f862a945'),
    'pcm-transfer': ('outputs/rk3568-audio-transfer-20261005/build/static-v1/pcm-transfer', 659736,
                     '2a6c765bd9c3c25b3456e60d68670231e81dcaf7781b827559cd701beed09e2e'),
    'pcm-peer-idle': (RUNTIME + 'pcm-peer-idle-v1/production-v2/pcm-peer-idle', 655136,
                      '7693a052b6318ec3e965451fcb94609e97cb48e693715b847b62032cc684e661'),
}
GUARD_MANIFEST = '15a24232ebaab58a5642aba2d8b92e66216208480fc7decae5ea776f6b8dbb18'
GUARD_INVENTORY = 'b45792270eda2881b3d5de06406bd42df0c6b34d80fc46505ffde42a31efc4dd'
CODEC_SOURCE = '72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64'
CODEC_HEADER = '370f2c9451d0e871b627c7b9a9b90cc24e486c49cebe29c068d5b692f7802449'


def runtime_sums(blobs):
    return ''.join(metadata(blob)['sha256'] + '  ' + name + '\n' for name, blob in sorted(blobs.items())).encode()


def checked_inventory(directory, expected_sha):
    name = directory + '/frozen-output-manifest.json'
    data = read_ordinary(relative_path(name), 8 * 1024 * 1024)
    require(metadata(data)['sha256'] == expected_sha, 'Runtime frozen inventory identity')
    record = unique_json(data)
    files = record.get('files_sha256')
    require(isinstance(files, dict) and files, 'Runtime complete frozen inventory')
    verify_hash_map({directory + '/' + relative: sha for relative, sha in files.items()})
    return {'path': name, **metadata(data), 'verified_files': len(files)}


def validate_codec_source_table(selected, complete, selections):
    directory_names = ['include', 'arch/arm64/include', 'scripts']
    expected = {name: row for name, row in complete.items() if name in selections or
                any(name.startswith(directory + '/') for directory in directory_names)}
    regular = {name: row for name, row in expected.items() if row['mode'] in ('100644', '100755')}
    links = {name: row for name, row in expected.items() if row['mode'] == '120000'}
    require(set(selected.get('regular_files_metadata', {})) == set(regular) and
            set(selected.get('known_SDK_internal_links', {})) == set(links), 'Codec finite source exact complete Image key set')
    for name, row in selected['regular_files_metadata'].items():
        require(row['sha256'] == regular[name]['sha256'] and row['bytes'] == regular[name]['bytes'] and
                bool(row['mode'] & 0o111) == (regular[name]['mode'] == '100755'), 'Codec source bytes/size/mode match complete Image')
    for name, row in selected['known_SDK_internal_links'].items():
        data = row['link_text'].encode()
        require(row['link_text_sha256'] == metadata(data)['sha256'] == links[name]['sha256'] and len(data) == links[name]['bytes'],
                'Codec selected frozen SDK file/directory link text matches complete Image')


def codec_abi_names():
    build = relative_path(IMAGE_BUILD)
    names = {'.config', 'Module.symvers', 'vmlinux.symvers', 'Makefile'}
    for name in names:
        path = build / name
        require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), 'Codec ABI ordinary core file')
    for directory in ('include', 'arch/arm64/include', 'scripts'):
        path = build / directory
        require(not path.is_symlink() and path.is_dir(), 'Codec ABI ordinary selected directory')
        for member in path.rglob('*'):
            mode = member.lstat().st_mode
            require(not member.is_symlink() and (stat.S_ISDIR(mode) or stat.S_ISREG(mode)), 'Codec ABI ordinary tree member')
            if stat.S_ISREG(mode):
                names.add(member.relative_to(build).as_posix())
    return names


def codec_auditor():
    source = relative_path(CODEC_BUILDER)
    data = read_ordinary(source)
    require(metadata(data)['sha256'] == 'ac8e0fabbb5ee9dee12b136e576560c98e2efe9484727db1227338507a5c1fee',
            'Codec auditor identity before execution')
    audit = ModuleType('audio_v5_actual_codec_elf')
    audit.__file__ = str(source)
    exec(compile(data, str(source), 'exec'), audit.__dict__)
    require(audit.SOURCE == relative_path(IMAGE_SOURCE) and audit.ABI == relative_path(IMAGE_BUILD), 'Embedded new codec auditor source/ABI paths')
    return audit, data


def codec_elf_info(binary, exports, vmlinux_exports):
    import uuid
    audit, data = codec_auditor()
    output = fresh_directory(HERE / 'build' / ('codec-elf-audit-v5-' + uuid.uuid4().hex))
    copied = output / 'snd-soc-rk817.ko'
    write_new(copied, binary)
    steps = []
    actual = audit.audit_module(copied, output, steps, exports, vmlinux_exports)
    require(read_ordinary(copied) == binary, 'ELF audit copied module bytes preserved')
    trace = {'module_input': metadata(binary), 'actual_info': actual, 'steps': steps,
             'auditor_source_sha256': metadata(data)['sha256'],
             'files_sha256': {p.name: metadata(read_ordinary(p))['sha256'] for p in sorted(output.iterdir()) if p.is_file()},
             'scope': 'ACTUAL_COPY_ELF_READELF_NM_NO_PRODUCTION_FILE_WRITE', 'board_tested': False}
    write_new(output / 'receipt.json', json_bytes(trace))
    return actual  # Actual ELF values only; fresh path/argv/time stay outside stable runtime identity.


def validate_codec(manifest, module, image, image_manifest_data, image_manifest):
    require(manifest.get('image_sha256') == metadata(image)['sha256'] == IMAGE_SHA and
            manifest.get('image_manifest_sha256') == metadata(image_manifest_data)['sha256'] == IMAGE_MANIFEST_SHA,
            'Codec exact actual completed new Image binding')
    require(manifest.get('status') == 'ACTUAL_COMPLETED_IMAGE_CODEC_ABI_VERIFIED' and
            type(manifest.get('build_exit_code')) is int and manifest['build_exit_code'] == 0 and
            manifest.get('source_sha256') == CODEC_SOURCE and manifest.get('header_sha256') == CODEC_HEADER and
            manifest.get('abi_unchanged') is True and manifest.get('original_ABI_and_finite_source_unchanged') is True and
            manifest.get('module_symvers_sha256') == image_manifest['module_symvers_sha256'] and
            manifest.get('vmlinux_symvers_sha256') == image_manifest['vmlinux_symvers_sha256'], 'Codec actual build/source/ABI binding')
    require(all(manifest.get(key) is False for key in ['board_tested', 'loaded', 'unload_tested', 'deployed', 'full_duplex_passed', 'accepted_for_board']) and
            manifest.get('modversions') is False and manifest.get('codec_exports') == {}, 'Codec offline/no-CRC-enforcement boundary')
    info = manifest.get('module', {})
    require(info == manifest.get('actual_module') and info.get('bytes') == len(module) and
            info.get('sha256') == metadata(module)['sha256'], 'Codec actual complete module fields/bytes')
    require(len(module) >= 64 and module[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<HH', module, 16) == (1, 183), 'Codec AArch64 ET_REL')
    expected_vermagic = image_manifest['kernel_release'] + ' SMP preempt_rt mod_unload aarch64'
    require(info.get('metadata', {}).get('vermagic') == [expected_vermagic] and
            b'vermagic=' + expected_vermagic.encode() + b'\0' in module, 'Codec exact vermagic')
    require(info.get('imports_resolved') is True and info.get('imports_from_actual_Module_and_vmlinux_symvers') is True and
            all(info.get(key) is False for key in ['elf_has_interp', 'elf_has_needed', 'MODVERSIONS_enabled',
                                                 '__versions_section_present', 'CRC_runtime_enforcement_claimed']),
            'Codec actual ELF/import and MODVERSIONS=n boundary')
    audit, auditor_data = codec_auditor()
    actual_builder_sha = metadata(auditor_data)['sha256']
    require(manifest.get('audit_source') == CODEC_BUILDER and manifest.get('audit_embedded_in_builder') is True and
            manifest.get('audit_source_sha256') == manifest.get('builder_sha256') == actual_builder_sha and
            metadata(read_ordinary(relative_path(CODEC_PATH + 'builder-snapshot.py')))['sha256'] == actual_builder_sha,
            'New codec embedded actual auditor and builder binding')
    exports = audit.symbols(relative_path(PRODUCTION + 'Module.symvers'))
    vmlinux_exports = audit.symbols(relative_path(PRODUCTION + 'vmlinux.symvers'))
    imports = info.get('imports')
    require(isinstance(imports, dict) and imports and
            all(exports.get(name) == vmlinux_exports.get(name) == value and value['provider'] == 'vmlinux' and not value['namespace']
                for name, value in imports.items()), 'Codec actual Module plus vmlinux import closure')
    selections = ['include', 'arch/arm64/include', 'scripts', '.config', 'Module.symvers', 'vmlinux.symvers', 'Makefile']
    require(manifest.get('actual_generated_ABI_selections') == selections and
            manifest.get('actual_config_sha256') == CONFIG and
            manifest.get('actual_Module_symvers_sha256') == image_manifest['module_symvers_sha256'] and
            manifest.get('actual_vmlinux_symvers_sha256') == image_manifest['vmlinux_symvers_sha256'],
            'Codec exact actual generated selections and core inputs')
    current = audit.inventory(relative_path(IMAGE_BUILD), selections)
    abi = manifest.get('abi_inventory')
    require(isinstance(abi, dict) and set(abi) == codec_abi_names() and abi == current['regular_files_sha256'],
            'Codec complete actual current ABI ordinary file set and bytes')
    root_receipt, root_receipt_identity = bound_json(ROOT_ABI + 'receipt.json', ROOT_ABI_RECEIPT)
    root_inventory, root_inventory_identity = bound_json(ROOT_ABI + 'inventory.json', ROOT_ABI_INVENTORY)
    require(root_receipt.get('root_current_generated_ABI_snapshot_completed') is True and
            root_receipt.get('image_sha256') == IMAGE_SHA and root_receipt.get('image_manifest_sha256') == IMAGE_MANIFEST_SHA and
            root_receipt.get('inventory_sha256') == ROOT_ABI_INVENTORY and
            root_receipt.get('actual_BUILD_selection_before_after_equal') is True and
            root_receipt.get('copied_bytes_sizes_modes_equal') is True and
            root_receipt.get('generated_inventory_was_signed_at_Image_compile_time') is False and
            root_inventory.get('files') == current['regular_files_metadata'], 'Root current precodec generated ABI equals actual selection')
    require(manifest.get('root_generated_ABI_receipt_sha256') == ROOT_ABI_RECEIPT and
            manifest.get('root_generated_ABI_inventory_sha256') == ROOT_ABI_INVENTORY and
            manifest.get('root_generated_ABI_scope') == root_receipt['scope'] and
            manifest.get('generated_inventory_was_signed_at_Image_compile_time') is False and
            manifest.get('actual_generated_ABI_regular_files') == len(abi) == root_receipt['ordinary_files'],
            'Codec exact root current snapshot binding, no compile-time signed-ABI claim')
    for name, identity in root_inventory['files'].items():
        path = relative_path(ROOT_ABI + 'snapshot/' + name)
        require(metadata(read_ordinary(path))['sha256'] == identity['sha256'] and path.stat().st_size == identity['bytes'] and
                stat.S_IMODE(path.lstat().st_mode) == identity['mode'], 'Root generated ABI ordinary snapshot bytes/size/mode')
    before, before_identity = bound_json(CODEC_PATH + 'before-ABI.json', manifest['ABI_inventory_sha256'])
    after = unique_json(read_ordinary(relative_path(CODEC_PATH + 'after-ABI.json')))
    require(before == after == current, 'Codec actual generated ABI before/after/current exact')
    shadow = audit.inventory(relative_path(CODEC_PATH + 'kernel-abi'), selections)
    require(shadow == before, 'Codec private shadow exact copied current generated ABI')
    source_selections = ['include', 'arch/arm64/include', 'scripts', 'Makefile', 'arch/arm64/Makefile',
                         'sound/soc/codecs/Makefile', 'sound/soc/codecs/Kconfig',
                         'sound/soc/codecs/rk817_codec.c', 'sound/soc/codecs/rk817_codec.h']
    source_before, source_identity = bound_json(CODEC_PATH + 'before-source-headers-scripts.json', manifest['source_inventory_sha256'])
    source_after = unique_json(read_ordinary(relative_path(CODEC_PATH + 'after-source-headers-scripts.json')))
    source_current = audit.inventory(relative_path(IMAGE_SOURCE), source_selections, True)
    require(manifest.get('actual_source_selections') == source_selections and manifest.get('source_selection_exact_keys_matched') is True and
            manifest.get('actual_compiled_codec_source_sha256') == CODEC_SOURCE and
            manifest.get('actual_compiled_codec_header_sha256') == CODEC_HEADER and manifest.get('compiler') == image_manifest['compiler'],
            'Codec actual source selection and compiled C/H/compiler identity')
    complete = unique_json(read_ordinary(relative_path(PRODUCTION + 'integrated-source-inventory.json')))
    validate_codec_source_table(source_current, complete, source_selections)
    require(source_before == source_after == source_current and manifest.get('source_selection_matched_complete_Image_inventory') is True and
            manifest.get('source_known_SDK_links') == source_current['known_SDK_internal_links'],
            'Codec actual finite source/headers/scripts before/after with frozen SDK file/directory links')
    for name, expected in [('rk817_codec.c', CODEC_SOURCE), ('rk817_codec.h', CODEC_HEADER)]:
        require(metadata(read_ordinary(relative_path(CODEC_PATH + 'modules/' + name)))['sha256'] == expected, 'Actual compiled codec source snapshot')
    primary = read_ordinary(relative_path(CODEC_PATH + 'modules/.rk817_codec.o.cmd'))
    require(metadata(primary)['sha256'] == manifest.get('actual_primary_Kbuild_command_sha256') and
            '-DMODULE' in primary.decode().splitlines()[0] and str(relative_path(CODEC_PATH + 'modules/rk817_codec.c')) in primary.decode().splitlines()[0],
            'Actual external codec source participation')
    require(info == codec_elf_info(module, exports, vmlinux_exports), 'Actual new complete copied ELF audit equality')
    return {'actual_ABI_files': len(abi), 'before_ABI': before_identity, 'source_selection': source_identity,
            'root_current_ABI_receipt': root_receipt_identity, 'root_current_ABI_inventory': root_inventory_identity,
            'generated_inventory_was_signed_at_Image_compile_time': False, 'MODVERSIONS_CRC_enforcement_claimed': False}


def runtime_inputs(image, image_manifest_data, image_manifest):
    blobs = {name: read_locked(*fields) for name, fields in RUNTIME_FIXED.items()}
    guard_dir = RUNTIME + 'session-guard-v4'
    guard_data = read_ordinary(relative_path(guard_dir + '/build/manifest.json'), 4 * 1024 * 1024)
    require(metadata(guard_data)['sha256'] == GUARD_MANIFEST, 'Guard v4 build manifest identity')
    guard = unique_json(guard_data)
    require(guard['binary_sha256'] == metadata(blobs['audio-session-guard'])['sha256'] and
            guard['inspector_sha256'] == metadata(blobs['alsa-inspect'])['sha256'], 'Guard v4 executable/inspector binding')
    guard_inventory = checked_inventory(guard_dir, GUARD_INVENTORY)
    codec_path = CODEC_PATH
    codec_data = read_ordinary(relative_path(codec_path + 'manifest.json'), 4 * 1024 * 1024)
    require(metadata(codec_data)['sha256'] == digest(CODEC_MANIFEST_SHA), 'Parent-notified actual new codec manifest identity')
    codec = unique_json(codec_data)
    blobs['snd-soc-rk817.ko'] = read_ordinary(relative_path(codec_path + 'modules/snd-soc-rk817.ko'))
    codec_proofs = validate_codec(codec, blobs['snd-soc-rk817.ko'], image, image_manifest_data, image_manifest)
    files = {name: {'path': RUNTIME_FIXED[name][0] if name in RUNTIME_FIXED else codec_path + 'modules/' + name,
                    **metadata(blob)} for name, blob in blobs.items()}
    record = {'files': files, 'codec_manifest': {'path': codec_path + 'manifest.json', **metadata(codec_data)},
              'guard_manifest': {'path': guard_dir + '/build/manifest.json', **metadata(guard_data)},
              'guard_inventory': guard_inventory, 'guard_version': 4, 'cpu_version': 12,
              'codec_actual_ABI_proofs': codec_proofs, 'pcm_peer_idle': peer_idle_proofs(),
              'cpu_source_sha256': CPU_SOURCE, 'cpu_manifest_sha256': CPU_MANIFEST, 'cpu_inventory_sha256': CPU_INVENTORY,
              'cpu_addendum_inventory_sha256': CPU_ADDENDUM_INVENTORY,
              'cpu_v12_candidate_ABI_files': 2020,
              'guard_v4_original_CPU_v10_input_kept': True,
              'guard_v4_sysfs_protocol_unchanged_by_CPU_v12': True,
              'guard_is_collector_not_START_authorization': True,
              'board_tested': False, 'physical_sound_verified': False, 'formal_flash_ready': False}
    return record, blobs


OFFICIAL_COMMIT = '99894068024224a62595e051d69e748e2499f52e'
LOCKS = {
    'third_party/linux-rk3588/Documentation/arm64/booting.rst': (12197, 'ed228088e1908ff94c1236f63efb46b4975b7dcd7bfede2cd059d83ea9d330d0'),
    PACKAGE + 'audit-boot.py': (15327, '4902a1281665d58f7e053838af5547522cc6f227c2be1baf6d260cf2ccd6067d'),
    PACKAGE + 'build-roundtrip.py': (8679, 'b485eaf390799c9af2de2b25e5a79c77db3b368de0e5784c6b08c620492b18fc'),
    PACKAGE + 'build-ram-candidate-v2.py': (11504, '298c0c6620ad0703d5566b233176cd276b0404e589d94152c9ae809ddb7eae1d'),
    PACKAGE + 'dt-semantics-v2.py': (5164, 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56'),
    PACKAGE + 'libfdt-v2.py': (5537, '9fdba61ae8d7d004ac7f24b7f116f6a314032c01624357f01619f609a5b8a954'),
    PACKAGE + 'build-uart-shim-v2.py': (4875, '3c00f046cb51bf49e83dccb2fa741d6a9d38db163a236b71c4dc653dd226d3ea'),
    PACKAGE + 'sources/mkbootimg.py': (13371, '5579fb6bcb9e89e790a70fb9ccf3c00cf56e3e46aef74d84fcb0964887e5576e'),
    PACKAGE + 'build/libfdt-v2/libfdt-locked.so': (45696, '03c8661fb005cd967c768332622c6aed6415dbcdce31939de26933e61b388a18'),
    PACKAGE + 'build/libfdt-v2/manifest.json': (4131, '9404a7d2e7e1070197e06f265b46db753e71586765e2a68f335ad8b6128bbe96'),
    RUNTIME + 'build-audio-ram-shim.py': (5573, '5aeb0f5f9cc7092cedc7f1975d9097a2e95f5bfa1e8b58fb27be09b64564b749'),
    RUNTIME + 'build/audio-ram-shim-v1/manifest.json': (3591, '9557c06318faa92380e736464032eaede8589f5af4335bab2c61282925fdd381'),
}
FIXED = {
    'original': ('outputs/rk3568-backup-linux-20261003/original/boot.img', SIZE,
                 '0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28'),
    'ramdisk': ('outputs/rk3568-pid1-20261005/build/production-v3/initramfs-pid1.cpio.gz', 972203,
                '54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef'),
    'rootfs': ('outputs/rk3568-pid1-20261005/build/production-v3/rootfs-pid1.ext4', 16777216,
               '3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d'),
    'dtb': (RUNTIME + 'build/audio-ram-shim-v1/audio-ram-shim.dtb', 163204,
            'c36b140c0ad18b79c3976f64239ef02251fc6986893afad7c474126725eb1e8b'),
    'audio_baseline': ('outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb', 163161,
                       '9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478'),
    'dtbo': ('outputs/rk3568-backup-linux-20261003/original/dtbo.img', 4194304,
             '59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d'),
}
APPLIED = (163285, '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f')


def require(value, message):
    if not value:
        raise ValueError(message)


def metadata(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'crc32': f'{zlib.crc32(data) & 0xffffffff:08x}'}


def relative_path(name):
    require(isinstance(name, str) and str(PurePosixPath(name)) == name and
            not name.startswith('/') and '\\' not in name and
            all(part not in ('', '.', '..') for part in name.split('/')), 'Repository relative path required')
    path = ROOT / name
    require(path == path.resolve() and path.is_relative_to(ROOT), 'Symlink/escaped input rejected: ' + name)
    return path


def read_ordinary(path, limit=64 * 1024 * 1024):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_relative_to(ROOT), 'Ordinary repository file required')
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit, 'Bounded ordinary file required')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(before.st_size + 1)
        after = os.fstat(descriptor)
        require(len(data) == before.st_size and
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                'Input changed during read')
        return data
    finally:
        os.close(descriptor)


def read_locked(name, size, sha):
    data = read_ordinary(relative_path(name))
    require(len(data) == size and metadata(data)['sha256'] == sha, 'Locked input changed: ' + name)
    return data


def unique_json(data):
    def pairs(items):
        result = {}
        for name, value in items:
            require(name not in result, 'Duplicate JSON key')
            result[name] = value
        return result
    def bad_constant(value):
        raise ValueError('Non-finite JSON number: ' + value)
    result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=bad_constant)
    require(isinstance(result, dict), 'JSON object required')
    return result


def digest(value):
    require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'Full lowercase SHA256 required')
    return value


def verify_hash_map(mapping):
    require(isinstance(mapping, dict) and bool(mapping), 'Nonempty source hash map required')
    for name, sha in mapping.items():
        data = read_ordinary(relative_path(name))
        require(metadata(data)['sha256'] == digest(sha), 'Reviewed file changed: ' + name)


@lru_cache(maxsize=1)
def dependencies():
    checked = {name: read_locked(name, size, sha) for name, (size, sha) in LOCKS.items()}
    lib_manifest = unique_json(checked[PACKAGE + 'build/libfdt-v2/manifest.json'])
    require(len(lib_manifest['sources']) == 13, 'Locked libfdt source count')
    for name, info in lib_manifest['sources'].items():
        path = PACKAGE + 'build/libfdt-v2/libfdt-source/' + name
        checked[path] = read_locked(path, info['bytes'], info['sha256'])
    modules = {}
    for name in ('audit-boot.py', 'build-roundtrip.py', 'build-ram-candidate-v2.py',
                 'dt-semantics-v2.py', 'libfdt-v2.py', 'build-uart-shim-v2.py'):
        path = relative_path(PACKAGE + name)
        module = ModuleType('audio_locked_' + name.replace('-', '_').replace('.', '_'))
        module.__file__ = str(path)
        exec(compile(checked[PACKAGE + name], str(path), 'exec'), module.__dict__)
        modules[name] = module
    return modules, checked


def overlaps(spans):
    result = []
    for index, (name, start, end) in enumerate(spans):
        for other, left, right in spans[index + 1:]:
            if max(start, left) < min(end, right):
                result.append({'left': name, 'right': other,
                               'intersection': [max(start, left), min(end, right)]})
    return result


def image_plan(image, header, component_sizes):
    require(len(image) >= 64 and image[56:60] == b'ARM\x64', 'ARM64 Image magic/header')
    require(set(component_sizes) == {'kernel', 'ramdisk', 'second', 'dtb'} and
            all(type(size) is int and size > 0 for size in component_sizes.values()),
            'Positive integer component sizes required')
    text_offset, image_size, flags = struct.unpack_from('<QQQ', image, 8)
    require(len(image) <= image_size <= 0xffffffffffffffff - 0x400000, 'ARM64 bounded effective memory size')
    require(flags & 1 == 0 and flags >> 4 == 0 and (flags >> 1) & 3 == 1,
            'ARM64 little-endian 4 KiB config/defined flag bits required')
    require(flags & 8 != 0, '4 MiB plan requires any-physical-base placement flag')
    require(text_offset <= 0x400000 and (0x400000 - text_offset) % 0x200000 == 0,
            'ARM64 text_offset/2 MiB base alignment')
    require(image[32:56] == bytes(24), 'ARM64 reserved header fields')
    spans = [('kernel', 0x400000, 0x400000 + image_size),
             ('fdt_workspace', 0xa100000, 0xa140000),
             ('initrd', 0x4000000, 0x4000000 + component_sizes['ramdisk']),
             ('package', 0x20000000, 0x22800000)]
    require(component_sizes['dtb'] <= 0x40000 and APPLIED[0] <= 0x40000,
            'FDT blob exceeds conservative workspace')
    require(component_sizes['ramdisk'] > 0, 'Empty initrd')
    require(not overlaps(spans), 'Candidate actual plan intervals overlap')
    # These are static constraints from the earlier trial, not a fresh bdinfo result.
    historical_banks = [[0x200000, 0x8400000], [0x9400000, 0xf0000000]]
    require(any(left <= 0x400000 - text_offset < right for left, right in historical_banks),
            'ARM64 aligned base outside historical usable bank')
    require(all(any(left <= start < end <= right for left, right in historical_banks)
                for _, start, end in spans), 'Candidate span outside historical bank constraints')
    header_spans = [(name, header[name + '_addr'], header[name + '_addr'] +
                     (image_size if name == 'kernel' else component_sizes[name]))
                    for name in ('kernel', 'ramdisk', 'second', 'dtb')]
    return {'image_header': {'text_offset': text_offset, 'image_size': image_size, 'flags': flags},
            'actual_plan': {name: [start, end] for name, start, end in spans},
            'actual_plan_overlaps': [], 'kernel_2m_aligned_base': 0x400000 - text_offset,
            'header_destination_intervals': {name: [start, end] for name, start, end in header_spans},
            'header_destination_overlaps': overlaps(header_spans),
            'header_addresses_are_actual_destinations': False,
            'old_fdt_memreserve': {'interval': [0xa100000, 0xa125000],
                'classification': 'SAME_PURPOSE_FDT_RESERVATION_INSIDE_GD_WORKSPACE'},
            'old_initrd_memreserve': {'interval': [0xa200000, 0xa2c8c20],
                'classification': 'UNCHANGED_OLD_ADDRESS_METADATA_NOT_CURRENT_INITRD'},
            'historical_bank_constraints': historical_banks,
            'fresh_bank_and_reserved_ranges_verified': False,
            'actual_destinations_verified': False,
            'gd_fdt_addr_must_equal_temporary_fdt_addr_r': 0xa100000,
            'fresh_gd_env_relocation_reserved_and_full_crc_required': True}


def validate_image_metadata(manifest, image):
    """Pure complete Image/header binding, also exercised without unavailable build artifacts."""
    info = metadata(image)
    require(type(manifest.get('image_bytes')) is int and manifest['image_bytes'] == info['bytes'] and
            digest(manifest['image_sha256']) == info['sha256'] and manifest.get('image_crc32') == info['crc32'],
            'Complete Image content binding')
    require(len(image) >= 64 and image[56:60] == b'ARM\x64', 'Manifest Image magic')
    require(type(manifest.get('text_offset')) is int and
            manifest['text_offset'] == struct.unpack_from('<Q', image, 8)[0] and
            type(manifest.get('image_memory_bytes')) is int and
            manifest['image_memory_bytes'] == struct.unpack_from('<Q', image, 16)[0], 'Manifest Image header binding')
    require(manifest.get('kernel_release') == '5.10.160-rt89-g9f9e9d18574d-dirty', 'Expected kernel release')
    return info


ASOC_DIRECTORY = RUNTIME + 'asoc-open-rollback-v1'
ASOC_MANIFEST_SHA = '9b3925f93a7c87dc43e2d5866e204f5384a43195c32fd083d641a709ee89d7a6'
ASOC_SEAL_SHA = 'bdcdb5081a0a770413d48fcfc839121ced7bceb32204c725dea1ec5351d7adf6'
ASOC_ROOT_SHA = '42fba37ab7c5d1ae17be9960189d0a325fa8b60359bd22c96011bdb325bdecff'
ASOC_FILES = {'sound/soc/soc-pcm.c', 'sound/soc/soc-component.c',
              'sound/soc/soc-compress.c', 'sound/soc/generic/simple-card-utils.c'}
ASOC_REMAINING_REDS = ['sequential_first_0_second_normal_START', 'sequential_first_1_second_normal_START',
                       'concurrent_two_normal_START_commit_both', 'hypothetical_dual_joint_STOP_reaches_global_proof']
IMAGE_SOURCE = '.deps/kernel-source/aiot-3568pq-audio-v4'
IMAGE_BUILD = '.deps/kernel/aiot-3568pq-audio-v4'
IMAGE_SHA = '48b9958d36e2b4821235520360530faac38c9f2dae072c2a2602dbda7e048595'
IMAGE_MANIFEST_SHA = '8df525843cac41fd0e272351bc41d0e573c25570cfed7e60f1990b9fe97aa33a'
IMAGE_INDEPENDENT_REVIEW = 'c62efed4dec4149028233c2cdec59815e56854d7bdad641844d1e8d5b8cf02cd'
PEER_INDEPENDENT_REVIEW = '454023ebb4a26d9e2327a8c43f400a2fef9203004a0e8486715efba7d19a2426'
CODEC_PATH = RUNTIME + 'codec-image-v4-v1/build-v2/'
CODEC_BUILDER = RUNTIME + 'codec-image-v4-v1/codec_builder.py'
CODEC_MANIFEST_SHA = '32241d1dfe9f2cbf17bae023065d87ee436173ba319a9f40b81ad5c7b1eb8e3c'  # Parent-notified actual build-v2.
ROOT_ABI = RUNTIME + 'build/root-image-v4-abi-v1/'
ROOT_ABI_RECEIPT = '2f25e37f2a30732ebd378c2874f1d7a3c3d37f19b7fe1d6486646bac61998e58'
ROOT_ABI_INVENTORY = 'bf3766426c2eb869442dc2703f6321eaad6143ebeaf63dad279c72eaf0f3e2a3'
PEER_DIRECTORY = RUNTIME + 'pcm-peer-idle-v1'
PEER_SOURCE = '4edc171fd8bb57c10d844bbfdfa72f83dd090de3f96f143bab8459fd7e22c8d2'
PEER_HEADER = '26ae04bc98a5e466bc24a18ab76b5841c9c52a0e265d5610cdedc2d4011536f9'
PEER_MANIFEST = '30e074fd01cbe94bc8e28a20de19698c5492525af469615afc7daaac92331779'
PEER_SEAL = 'c02ff1af64506a77f0920a32095d93c53991d9c6d9026e33e075eaf256569c39'
PEER_INVENTORY = '952270f37505769e24195b826636e89ebe5c23c5b424670db5047ef91b743ac9'
PEER_SUMS = '7ebbea24c05ecbd6a6c15a9d4012e49295d7c71d98db491e096fbf82338837e4'
PEER_REVIEW = '569f6ed7e09e58c82eb9a9388fddb8f928d8b9df855d86fdf20e4b10ef02b69d'
PEER_ROOT_AUDIT = 'b6fdd92a5236b70deb4678e861a22df826e38420c2fb03a48f8ad9fe23aaff52'
REQUIRED_BEFORE_EXECUTION = ['fresh bdinfo/banks/gd/env', 'fresh reserved/relocation intervals',
    'full padded SHA/CRC and actual transfer addresses', 'one-argument bootm from main controller']
BOARD_RUNTIME_PROOF_REQUIRED = ['final FDT whole tree and overlay', 'new live Image identity',
    'bounded PCM lifecycle/readonly state', 'ordinary reboot and unchanged protected Android hashes']


def bound_json(name, expected, limit=64 * 1024 * 1024):
    data = read_ordinary(relative_path(name), limit)
    require(metadata(data)['sha256'] == digest(expected), 'Exact evidence identity: ' + name)
    return unique_json(data), {'path': name, **metadata(data)}


def validate_patch_declaration(applied, expected):
    require(isinstance(applied, list) and applied == expected, 'Image exact ordered public14 plus privateASoC1 patch series')


def validate_asoc_run(version, row):
    require(version in ('red', 'green'), 'ASoC model version')
    require(row.get('production_functions_verified') == (68 if version == 'red' else 70) and
            set(row.get('runs', {})) == {'host', 'asan-ubsan', 'aarch64-qemu'}, 'ASoC exact extracted functions/environments')
    failures = ASOC_REMAINING_REDS if version == 'green' else None
    expected = {'contract_total': 25, 'contract_passed': 21 if version == 'green' else 0,
                'boundary_total': 110, 'boundary_passed': 110}
    for run in row['runs'].values():
        require(run.get('counts') == expected and run.get('compile', {}).get('exit') == 0 and
                run.get('execution', {}).get('exit') == 1 and run.get('complete_observation_log_matches_author') is True,
                'ASoC finite business and observation boundary')
        require(run.get('remaining_failures') == failures if failures is not None else
                isinstance(run.get('remaining_failures'), list) and len(run['remaining_failures']) == 25,
                'ASoC exact remaining business reds')


def validate_source_records(public, integrated, source_manifest, source_sizes):
    require(isinstance(public, dict) and len(public) == 89423 and isinstance(integrated, dict), 'Complete 89423 tracked source inventory')
    require(set(source_manifest.get('files', {})) == ASOC_FILES and set(source_sizes) == ASOC_FILES and
            all(source_manifest.get(key) is False for key in ['headers_struct_ABI_changed', 'CPU_v12_modified', 'START_gates_modified']),
            'Exact four ASoC source files without CPU/START/struct ABI change')
    expected = dict(public)
    for name, entry in source_manifest['files'].items():
        require(public[name]['sha256'] == digest(entry['original_sha256']), 'ASoC baseline is the public replay')
        expected[name] = {**public[name], 'sha256': digest(entry['sha256']), 'bytes': source_sizes[name]}
    require(integrated == expected, 'Integrated source is exactly public replay plus four reviewed files')


def verify_actual_tracked_source(expected):
    """Read actual current tracked bytes/mode/link text; this does not modify a checkout."""
    import subprocess
    tree = relative_path(IMAGE_SOURCE)
    require(subprocess.check_output(['git', '-C', str(tree), 'rev-parse', 'HEAD']).decode().strip() == COMMIT,
            'Actual Image source pinned commit')
    listing = subprocess.check_output(['git', '-C', str(tree), 'ls-files', '-s', '-z'])
    actual = {}
    for record in listing.split(b'\0'):
        if not record:
            continue
        index, raw_name = record.split(b'\t', 1)
        mode, unused_oid, stage = index.decode().split()
        name = raw_name.decode()
        require(stage == '0' and mode in ('100644', '100755', '120000') and name not in actual and name in expected,
                'Actual tracked source stage/type/set')
        path = tree / name
        require(str(PurePosixPath(name)) == name and not name.startswith('/') and '\\' not in name and
                all(part not in ('', '.', '..') for part in name.split('/')) and path.parent == path.parent.resolve(),
                'Canonical tracked source name and ordinary directory ancestry')
        if mode == '120000':
            require(stat.S_ISLNK(path.lstat().st_mode) and path.resolve().is_relative_to(tree),
                    'Bound SDK internal link only')
            data = os.readlink(path).encode()
        else:
            require(bool(path.lstat().st_mode & 0o111) == (mode == '100755'), 'Actual tracked source executable mode')
            data = read_ordinary(path)
        actual[name] = {'bytes': len(data), 'mode': mode, 'sha256': metadata(data)['sha256']}
    require(actual == expected, 'Actual complete tracked source bytes/modes/links equal integrated inventory')
    return len(actual)


def asoc_proofs(gate):
    require(all(gate.get(key) is True for key in ['asoc_independent_review_completed', 'asoc_root_fresh_models_completed',
                'asoc_actual_Kbuild_completed', 'public_14_integration_review_completed']), 'ASoC/public completed source/model/Kbuild/review')
    require(gate.get('public_patch_count') == 14 and gate.get('private_ASoC_patch_count') == 1 and
            gate.get('asoc_contract_passed') == 21 and gate.get('asoc_contract_total') == 25 and
            gate.get('asoc_boundary_observations_passed') == 110 and gate.get('asoc_boundary_unique_labels') == 74 and
            all(gate.get(key) is False for key in ['compressed_branch_Kconfig_generated', 'compressed_branch_ABI_validated', 'duplex_START_allowed']),
            'ASoC finite accepted profile retains four business reds')
    manifest, manifest_identity = bound_json(gate['asoc_source_manifest'], ASOC_MANIFEST_SHA)
    require(gate['asoc_source_manifest'] == ASOC_DIRECTORY + '/source-manifest-v1.json' and
            gate['asoc_source_directory'] == ASOC_DIRECTORY + '/source-v1' and
            gate['asoc_patch'] == ASOC_DIRECTORY + '/candidate-v1.patch', 'Exact private ASoC input paths')
    seal, seal_identity = bound_json(ASOC_DIRECTORY + '/sealed-v1/receipt.json', ASOC_SEAL_SHA)
    require(seal.get('source_manifest_sha256') == ASOC_MANIFEST_SHA and
            seal.get('source_sha256') == {name: entry['sha256'] for name, entry in manifest['files'].items()} and
            seal.get('patch_sha256') == manifest['patch_sha256'] and seal.get('remaining_business_reds') == ASOC_REMAINING_REDS and
            all(seal.get(key) is False for key in ['CPU_v12_modified', 'board_tested', 'full_duplex_passed', 'duplex_START_authorized',
                                                 'compressed_branch_Kconfig_generated', 'compressed_branch_ABI_validated']),
            'ASoC frozen source and finite boundary')
    inventory, inventory_identity = bound_json(ASOC_DIRECTORY + '/sealed-v1/file-manifest.json', seal['file_manifest_sha256'])
    verify_hash_map({ASOC_DIRECTORY + '/' + name: value for name, value in inventory['files_sha256'].items()})
    sums = read_ordinary(relative_path(ASOC_DIRECTORY + '/sealed-v1/SHA256SUMS'))
    require(metadata(sums)['sha256'] == seal['SHA256SUMS_sha256'], 'ASoC seal checksum identity')
    root, root_identity = bound_json(RUNTIME + 'build/root-asoc-candidate-v2/result.json', ASOC_ROOT_SHA)
    require(root.get('root_fresh_compile_and_execution') is True and root.get('all_six_fresh_compiles_and_runs_match') is True and
            root.get('root_runner_sha256') == seal['root_runner_sha256'] and set(root.get('versions', {})) == {'red', 'green'} and
            root.get('model_only') is True and all(root.get(key) is False for key in ['board_tested', 'full_duplex_passed', 'duplex_START_authorized']),
            'ASoC root fresh finite executions')
    for version, row in root['versions'].items():
        validate_asoc_run(version, row)
        for environment, run in row['runs'].items():
            directory = RUNTIME + 'build/root-asoc-candidate-v2/' + version + '/'
            require(metadata(read_ordinary(relative_path(directory + 'caller-chain-' + environment)))['sha256'] == digest(run['binary_sha256']),
                    'ASoC root actually executed ELF')
            for suffix in ['stdout', 'stderr']:
                require(metadata(read_ordinary(relative_path(directory + environment + '.' + suffix)))['sha256'] == run['execution'][suffix + '_sha256'],
                        'ASoC root raw execution output')
    review_name = RUNTIME + 'REVIEW-ASOC-OPEN-ROLLBACK-20261006.md'
    review, review_identity = read_ordinary(relative_path(review_name)), None
    require(metadata(review)['sha256'] == gate['files_sha256'].get(review_name), 'ASoC independent acceptance note')
    return manifest, {'source_manifest': manifest_identity, 'seal': seal_identity,
                      'file_manifest': inventory_identity, 'verified_frozen_files': len(inventory['files_sha256']),
                      'root_fresh': root_identity, 'independent_review': {'path': review_name, **metadata(review)},
                      'green_contract': [21, 25], 'boundary_observations': [110, 110], 'boundary_unique_labels': 74,
                      'remaining_business_reds': ASOC_REMAINING_REDS, 'duplex_START_authorized': False,
                      'compressed_branch_ABI_validated': False, 'board_tested': False}


def validate_peer_records(production, seal, audit):
    require(production.get('source_sha256') == PEER_SOURCE and production.get('parameters_header_sha256') == PEER_HEADER and
            production.get('binary_sha256') == RUNTIME_FIXED['pcm-peer-idle'][2] and production.get('binary_bytes') == 655136 and
            production.get('static_AArch64_ELF') is True and production.get('source_static_ABI_assertions_passed') is True and
            production.get('exit') == 0 and production.get('START_permission') is False and production.get('board_tested') is False,
            'Peer actual static production identity/boundary')
    require(seal.get('frozen') is True and seal.get('root_review_completed') is True and seal.get('independent_review_completed') is True and
            seal.get('source_sha256') == PEER_SOURCE and seal.get('parameters_header_sha256') == PEER_HEADER and
            seal.get('binary_sha256') == production['binary_sha256'] and seal.get('production_manifest_sha256') == PEER_MANIFEST and
            seal.get('inventory_sha256') == PEER_INVENTORY and seal.get('root_acceptance_sha256') == PEER_REVIEW and
            seal.get('frames_transferred') == 0 and seal.get('PREPARE_or_START_permission') is False and seal.get('board_tested') is False and
            seal.get('kernel_PM_DMA_or_shared_sysclk_proven') is False, 'Peer accepted no-START frozen evidence')
    require(audit.get('root_fresh_seal_audit_passed') is True and audit.get('archive_source_copies_byte_equal') is True and
            audit.get('seal_files_sha256') == {'receipt.json': PEER_SEAL, 'inventory.json': PEER_INVENTORY, 'SHA256SUMS': PEER_SUMS} and
            audit.get('ordinary_archive_files_readback') == seal.get('ordinary_archive_files') == 18771 and
            audit.get('ordinary_external_inputs_rechecked') == 9337 and audit.get('checksum_rows_rechecked') == 18773 and
            audit.get('binary_sha256') == production['binary_sha256'] and audit.get('hardware_operated') is False and
            audit.get('PREPARE_or_START_permission') is False, 'Peer root fresh complete seal audit')


def peer_idle_proofs():
    production, production_identity = bound_json(PEER_DIRECTORY + '/production-v2/manifest.json', PEER_MANIFEST)
    seal, seal_identity = bound_json(PEER_DIRECTORY + '/sealed-evidence-v1/receipt.json', PEER_SEAL)
    audit, audit_identity = bound_json(RUNTIME + 'build/root-peer-idle-seal-audit-v1.json', PEER_ROOT_AUDIT)
    validate_peer_records(production, seal, audit)
    review, review_identity = bound_json(RUNTIME + 'build/peer-idle-seal-independent-review-v1.json', PEER_INDEPENDENT_REVIEW)
    require(review.get('accepted_for_offline_package_input') is True and review.get('blocking_findings') == [] and
            review.get('receipt_sha256') == PEER_SEAL and review.get('inventory_sha256') == PEER_INVENTORY and
            review.get('SHA256SUMS_sha256') == PEER_SUMS and review.get('actual_root_cases_raw_reparsed') == 3096 and
            review.get('raw_stdout_stderr_bytes_equal_author') is True and review.get('PREPARE_or_START_permission') is False and
            review.get('board_tested') is False and review.get('timer_guarantees_D_state_or_stdout_deadline') is False,
            'Peer final independent byte archive and execution acceptance')
    inventory, inventory_identity = bound_json(PEER_DIRECTORY + '/sealed-evidence-v1/inventory.json', PEER_INVENTORY)
    archive = relative_path(PEER_DIRECTORY + '/sealed-evidence-v1')
    names = {item.relative_to(archive).as_posix() for item in archive.rglob('*') if item.is_file() or item.is_symlink()}
    require(names == set(inventory['files']) | {'receipt.json', 'inventory.json', 'SHA256SUMS'}, 'Peer exact byte archive ordinary file set')
    for name, identity in inventory['files'].items():
        blob = read_ordinary(relative_path(PEER_DIRECTORY + '/sealed-evidence-v1/' + name))
        require(len(blob) == identity['size'] and metadata(blob)['sha256'] == digest(identity['sha256']), 'Peer archived bytes: ' + name)
    sums = read_ordinary(archive / 'SHA256SUMS')
    require(metadata(sums)['sha256'] == PEER_SUMS, 'Peer exact checksum list identity')
    verify_hash_map({PEER_DIRECTORY + '/pcm-peer-idle.c': PEER_SOURCE, PEER_DIRECTORY + '/parameters.h': PEER_HEADER,
                     RUNTIME + 'REVIEW-PCM-PEER-IDLE-20261006.md': PEER_REVIEW,
                     'third_party/linux-rk3588/include/uapi/sound/asound.h': '138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447'})
    for key in ['author_actual_environments', 'root_actual_environments']:
        expected = {name: ([1032, 1032] if key.startswith('author') else {'passed': 1032, 'total': 1032})
                    for name in ['host', 'asan-ubsan', 'aarch64-qemu']}
        require(seal.get(key) == expected, 'Peer accepted actual three environments')
    return {'production_manifest': production_identity, 'seal': seal_identity, 'inventory': inventory_identity,
            'root_fresh_seal_audit': audit_identity, 'independent_seal_review': review_identity,
            'verified_archive_files': len(inventory['files']),
            'source_sha256': PEER_SOURCE, 'parameters_header_sha256': PEER_HEADER,
            'open_close_orders': 4, 'PREPARE_or_START_permission': False, 'board_tested': False,
            'kernel_PM_DMA_or_shared_sysclk_proven': False, 'timer_boundary': seal['timer_boundary']}


def validate_review(manifest, gate, gate_data, image):
    require(gate.get('accepted_for_offline_integration') is True and gate.get('cpu_v12_independent_review_completed') is True,
            'Independent C3/CPU v12 integration gate required')
    require(metadata(gate_data)['sha256'] == REVIEW_GATE_SHA, 'Exact completed public14 plus ASoC review gate')
    bound = gate.get('files_sha256')
    verify_hash_map(bound)
    require(manifest.get('reviewed_files_sha256') == bound and manifest.get('review_gate_sha256') == REVIEW_GATE_SHA,
            'Image review gate binding')
    require(manifest.get('source_commit') == COMMIT and manifest.get('source') == IMAGE_SOURCE and manifest.get('build') == IMAGE_BUILD and
            manifest.get('config_sha256') == CONFIG and manifest.get('cpu_source_sha256') == CPU_SOURCE and
            manifest.get('codec_source_sha256') == CODEC_SOURCE and
            all(manifest.get(key) is False for key in ['battery_algorithm_enabled', 'compressed_audio_enabled', 'duplex_START_gates_relaxed']),
            'Image actual source/config/single-START profile')
    require(type(manifest.get('build_exit_code')) is int and manifest['build_exit_code'] == 0 and
            manifest.get('original_clean') is True and manifest.get('deployed') is False and manifest.get('board_tested') is False,
            'Successful offline Image build required')
    source_manifest, asoc = asoc_proofs(gate)
    expected_patches = []
    for number in range(1, 15):
        matches = sorted((ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches').glob(f'{number:04d}-*.patch'))
        require(len(matches) == 1, 'Unique public patch required')
        name = matches[0].relative_to(ROOT).as_posix()
        actual = metadata(read_ordinary(matches[0]))['sha256']
        require(bound.get(name) == actual, 'Image public patch gate binding')
        expected_patches.append({'path': name, 'sha256': actual})
    expected_patches.append({'path': gate['asoc_patch'], 'sha256': digest(source_manifest['patch_sha256'])})
    require(metadata(read_ordinary(relative_path(gate['asoc_patch'])))['sha256'] == bound.get(gate['asoc_patch']) == source_manifest['patch_sha256'],
            'Private ASoC patch review binding')
    validate_patch_declaration(manifest.get('patches'), expected_patches)
    require(manifest.get('asoc_source_manifest_sha256') == ASOC_MANIFEST_SHA and manifest.get('complete_public_source_verified') == 89423 and
            manifest.get('asoc_changed_files') == sorted(ASOC_FILES), 'Image exact four-source manifest binding')
    public_reference = unique_json(read_ordinary(relative_path(gate['public_tracked_source_inventory'])))
    public, public_identity = bound_json(PRODUCTION + 'public-source-inventory.json', manifest['public_source_inventory_sha256'])
    integrated, integrated_identity = bound_json(PRODUCTION + 'integrated-source-inventory.json', manifest['integrated_source_inventory_sha256'])
    require(public == public_reference, 'Image public tracked source equals accepted complete replay')
    source_sizes = {name: len(read_ordinary(relative_path(gate['asoc_source_directory'] + '/' + name))) for name in ASOC_FILES}
    validate_source_records(public, integrated, source_manifest, source_sizes)
    verified_sources = verify_actual_tracked_source(integrated)
    for name, expected in CPU_FILES.items():
        require(bound.get(name) == expected and metadata(read_ordinary(relative_path(name)))['sha256'] == expected, 'CPU v12 frozen input unchanged')
    require(integrated['sound/soc/rockchip/rockchip_i2s_tdm.c']['sha256'] == CPU_SOURCE and
            integrated['sound/soc/codecs/rk817_codec.c']['sha256'] == CODEC_SOURCE, 'Image retained CPU and codec source')
    builder = RUNTIME + 'build-audio-image-v4.py'
    require(metadata(read_ordinary(relative_path(builder)))['sha256'] == bound.get(builder) == digest(manifest['builder_sha256']), 'Image new builder binding')
    require(manifest.get('compiler') == 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0', 'Image compiler binding')
    validate_image_metadata(manifest, image)
    require(metadata(image)['sha256'] == IMAGE_SHA, 'Parent-notified actual completed Image identity')
    require(metadata(read_ordinary(relative_path(PRODUCTION + 'kernel.config')))['sha256'] == CONFIG, 'Actual Image config file')
    for name, key in [('Module.symvers', 'module_symvers_sha256'), ('vmlinux.symvers', 'vmlinux_symvers_sha256')]:
        require(metadata(read_ordinary(relative_path(PRODUCTION + name)))['sha256'] == digest(manifest[key]), 'Exact Image symbol table binding')
    build = unique_json(read_ordinary(relative_path(PRODUCTION + 'build.command.json')))
    require(build.get('exit') == 0 and build.get('argv') == manifest.get('build_argv'), 'Actual complete Image/modules command')
    for suffix in ['stdout', 'stderr']:
        require(metadata(read_ordinary(relative_path(PRODUCTION + 'build.' + suffix)))['sha256'] == digest(build[suffix + '_sha256']), 'Actual Image build diagnostic stream')
    review, review_identity = bound_json(PRODUCTION + 'independent-review.json', IMAGE_INDEPENDENT_REVIEW)
    require(review.get('accepted_for_offline_complete_Image') is True and review.get('blocking_findings') == [] and
            review.get('image_sha256') == IMAGE_SHA and review.get('image_manifest_sha256') == IMAGE_MANIFEST_SHA and
            review.get('source_inventory_entries_rechecked') == verified_sources and review.get('only_four_ASoC_inventory_entries_differ') is True and
            review.get('CPU_v12_and_codec_sources_unchanged') is True and review.get('reviewed_inputs_rechecked') == len(bound) and
            review.get('current_generated_ABI_inventory_sha256') == ROOT_ABI_INVENTORY and
            review.get('current_generated_ABI_receipt_sha256') == ROOT_ABI_RECEIPT and
            all(review.get(key) is False for key in ['generated_inventory_signed_at_Image_compile_time', 'board_tested', 'START_authorized',
                                                   'full_duplex_passed', 'formal_flash_ready']), 'Image final independent actual input/source acceptance')
    return {'review_gate': metadata(gate_data), 'reviewed_files_sha256': bound,
            'patches_sha256': {row['path']: row['sha256'] for row in expected_patches}, 'ordered_patches': expected_patches,
            'builder_sha256': manifest['builder_sha256'], 'public_source_inventory': public_identity,
            'integrated_source_inventory': integrated_identity, 'actual_tracked_sources_verified': verified_sources,
            'asoc_proofs': asoc, 'cpu_v12_proofs': cpu_v12_proofs(gate), 'Image_independent_review': review_identity,
            'duplex_START_allowed': False, 'compressed_branch_ABI_validated': False, 'board_tested': False}


def production_inputs(review_gate):
    dependencies()
    manifest_data = read_ordinary(relative_path(PRODUCTION + 'manifest.json'), 4 * 1024 * 1024)
    gate_data = read_ordinary(relative_path(review_gate), 4 * 1024 * 1024)
    require(metadata(manifest_data)['sha256'] == IMAGE_MANIFEST_SHA, 'Parent-notified actual completed Image manifest identity')
    manifest, gate = unique_json(manifest_data), unique_json(gate_data)
    image = read_ordinary(relative_path(PRODUCTION + 'Image'))
    provenance = validate_review(manifest, gate, gate_data, image)
    runtime, blobs = runtime_inputs(image, manifest_data, manifest)
    return {'kernel': image, 'runtime': runtime, 'runtime_blobs': blobs, 'mode': 'RAM_ONLY_NOT_FLASH_READY',
            'image_manifest': {'path': PRODUCTION + 'manifest.json', **metadata(manifest_data)},
            'review_gate': {'path': review_gate, **metadata(gate_data)}, 'provenance': provenance}


def fixed_inputs():
    return {name: read_locked(*fields) for name, fields in FIXED.items()}


def inspect_candidate(data, image_inputs):
    modules, checked = dependencies()
    require(len(data) == SIZE, 'Candidate complete 40 MiB required')
    require(image_inputs['mode'] in ('RAM_ONLY_NOT_FLASH_READY', 'FIXTURE_ONLY_NOT_DEPLOYABLE'),
            'Explicit production or fixture mode required')
    audit = modules['audit-boot.py']
    report = audit.inspect_boot(data, expected_concat_count=1)
    fixed = fixed_inputs()
    original = audit.inspect_boot(fixed['original'])
    expected = {'kernel': metadata(image_inputs['kernel']), 'ramdisk': metadata(fixed['ramdisk']),
                'dtb': metadata(fixed['dtb'])}
    for component in report['components']:
        if component['name'] in expected:
            require(all(component[key] == value for key, value in expected[component['name']].items()),
                    'Locked component policy: ' + component['name'])
    header = report['header']
    for name in ('version', 'header_size', 'page_size', 'kernel_addr', 'ramdisk_addr', 'second_addr',
                 'tags_addr', 'dtb_addr', 'os_version_encoded', 'board'):
        require(header[name] == original['header'][name], 'Original header metadata policy: ' + name)
    require(header['cmdline'] == CMDLINE, 'Fixed Linux cmdline policy')
    entries, old = report['resource']['entries'], original['resource']['entries']
    require([entry['path'] for entry in entries] == [entry['path'] for entry in old], 'Original RSCE names/order policy')
    end = 12 * 512
    for entry, prior in zip(entries, old):
        require(entry['offset'] == end, 'Canonical RSCE offset policy')
        end += (entry['bytes'] + 511) & ~511
        selected = expected['dtb'] if entry['path'].endswith('.dtb') else prior
        require(all(entry[key] == selected[key] for key in ('bytes', 'sha256', 'crc32')), 'RSCE content policy: ' + entry['path'])
    require(report['components'][2]['bytes'] == end, 'RSCE exact extent policy')
    expected_raw = header['page_size'] + sum((component['bytes'] + header['page_size'] - 1) & ~(header['page_size'] - 1)
                                            for component in report['components'])
    require(report['raw_bytes'] == expected_raw <= SIZE, 'Dynamic raw extent policy')
    sizes = {component['name']: component['bytes'] for component in report['components']}
    plan = image_plan(image_inputs['kernel'], header, sizes)
    semantic = modules['dt-semantics-v2.py']
    baseline, shim = semantic.parse(fixed['audio_baseline']), semantic.parse(fixed['dtb'])
    shim_diff = {'/__symbols__:chosen': {'before': None, 'after': b'/chosen\0'.hex()},
                 '/chosen:phandle': {'before': None, 'after': '000002fa'}}
    require(semantic.diff(baseline, shim) == shim_diff, 'Exactly two audio shim prerequisites')
    handles = semantic.phandles(baseline)
    require(len(baseline['nodes']) == 962 and len(handles) == 761 and max(handles) == 0x2f9 and
            semantic.phandles(shim)[0x2fa] == '/chosen', 'Audio phandle/count policy')
    bridge = modules['libfdt-v2.py']
    entry = modules['build-uart-shim-v2.py'].overlay_entry(fixed['dtbo'])
    apply_report, applied = bridge.RealLibFdt().apply(fixed['dtb'], entry)
    require(apply_report['status'] == 0 and applied is not None, 'Real libfdt audio overlay')
    require((len(applied), metadata(applied)['sha256']) == APPLIED, 'Applied audit-only DT identity')
    tree = semantic.parse(applied)
    reboot = [key.rsplit(':', 1)[0] for key in baseline['properties'] if key.endswith(':mode-normal')]
    require(len(reboot) == 1, 'Unique normal reboot node')
    difference = semantic.overlay_diff(reboot[0])
    difference['/chosen:phandle'] = shim_diff['/chosen:phandle']
    require(semantic.diff(baseline, tree) == difference and tree['properties'][reboot[0] + ':mode-normal'] == '5242c300',
            'Complete five-property audio overlay transition')
    require(all(semantic.phandles(tree).get(handle) == name for handle, name in handles.items()),
            'Existing phandles preserved')
    report.update({'mode': image_inputs['mode'], 'board_tested': False, 'deployed': False,
                   'flash_authorized': False, 'saveenv': False, 'formal_flash_ready': False,
                   'usb_recovery_confirmed': False, 'package_early_dt_compatibility_verified': False,
                   'early_uboot_dtb': 'UNCHANGED_EMMC_ORIGINAL_FOR_RAM_TRIAL',
                   'address_analysis': plan, 'rootfs': metadata(fixed['rootfs']),
                   'native_pid1_old_rcu_image_check_is_new_image_identity': False,
                   'real_overlay': {'apply': apply_report, 'full_semantic_diff': difference,
                                    'applied_audit_only': metadata(applied), 'libfdt_sha256': bridge.LIB_SHA},
                   'packaged_dtb_is_pre_overlay_shim': True,
                   'dependency_files': {name: metadata(blob) for name, blob in checked.items()}})
    return report


def fresh_directory(output):
    path = Path(output).absolute()
    require(path == path.resolve() and path.is_relative_to(HERE / 'build') and path != HERE / 'build',
            'Fresh ordinary output inside own build required')
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_new(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def json_bytes(value):
    return (json.dumps(value, indent=2) + '\n').encode('utf-8')


def construct_package(out, image_inputs):
    """Internal mechanical path shared by the production CLI and labeled test fixtures."""
    modules, checked = dependencies()
    fixed = fixed_inputs()
    original = modules['audit-boot.py'].inspect_boot(fixed['original'])
    payloads = {'kernel': image_inputs['kernel'], 'ramdisk': fixed['ramdisk'], 'dtb': fixed['dtb']}
    payloads['second'] = modules['build-ram-candidate-v2.py'].build_resource(fixed['original'], original, fixed['dtb'])
    image_plan(payloads['kernel'], original['header'], {name: len(blob) for name, blob in payloads.items()})
    projected = 2048 + sum((len(blob) + 2047) & ~2047 for blob in payloads.values())
    require(projected <= SIZE, 'Audio package exceeds 40 MiB')
    require(image_inputs['mode'] != 'RAM_ONLY_NOT_FLASH_READY' or
            set(image_inputs.get('runtime_blobs', {})) == set(RUNTIME_FIXED) | {'snd-soc-rk817.ko'}, 'Complete production runtime sidecars required')
    output = fresh_directory(out)
    if image_inputs['mode'] == 'RAM_ONLY_NOT_FLASH_READY':
        runtime = output / 'runtime'
        runtime.mkdir()
        for name, blob in image_inputs['runtime_blobs'].items():
            write_new(runtime / name, blob)
        write_new(runtime / 'SHA256SUMS', runtime_sums(image_inputs['runtime_blobs']))
    components = output / 'components'
    components.mkdir()
    for name, blob in payloads.items():
        write_new(components / name, blob)
    official = modules['build-roundtrip.py'].official_module(relative_path(PACKAGE + 'sources/mkbootimg.py'))
    header = original['header']
    with ExitStack() as stack:
        stream = stack.enter_context((output / 'boot-raw.img').open('xb'))
        files = {name: stack.enter_context((components / name).open('rb')) for name in payloads}
        args = SimpleNamespace(output=stream, **files, recovery_dtbo=None, header_version=2,
                               pagesize=2048, base=0, kernel_offset=header['kernel_addr'],
                               ramdisk_offset=header['ramdisk_addr'], second_offset=header['second_addr'],
                               tags_offset=header['tags_addr'], dtb_offset=header['dtb_addr'],
                               os_version=header['os_version'], os_patch_level=header['os_patch_level'],
                               board=header['board'], cmdline=CMDLINE)
        official.write_header(args)
        official.write_data(args, 2048)
        stream.flush()
        os.fsync(stream.fileno())
    raw = read_ordinary(output / 'boot-raw.img')
    require(len(raw) == projected, 'Official writer raw extent disagreement')
    padded = raw + bytes(SIZE - len(raw))
    report = inspect_candidate(padded, image_inputs)
    write_new(output / 'boot-padded.img', padded)
    write_new(output / 'audit.json', json_bytes(report))
    snapshot = output / 'source-inputs'
    snapshot.mkdir()
    snapshots = dict(checked)
    for name in ('audio-package-v5.py',):
        relative = str((HERE / name).relative_to(ROOT))
        snapshots[relative] = read_ordinary(HERE / name)
    for name, blob in snapshots.items():
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_new(path, blob)
    manifest = {'schema': 1, 'status': image_inputs['mode'], 'board_tested': False, 'deployed': False,
                'flash_authorized': False, 'saveenv': False, 'formal_flash_ready': False,
                'original': {'path': FIXED['original'][0], **metadata(fixed['original'])},
                'inputs': {name: {'path': fields[0], **metadata(fixed[name])} for name, fields in FIXED.items()
                           if name != 'original'}, 'image_input': {key: value for key, value in image_inputs.items() if key not in ('kernel', 'runtime_blobs')},
                'kernel': metadata(image_inputs['kernel']), 'cmdline': CMDLINE,
                'rootfs_board_path': '/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4',
                'native_pid1_old_rcu_image_check_is_new_image_identity': False,
                'artifacts': {'boot-raw.img': metadata(raw), 'boot-padded.img': metadata(padded)},
                'components': {name: metadata(blob) for name, blob in payloads.items()},
                'official_commit': OFFICIAL_COMMIT, 'official_functions': ['write_header', 'write_data'],
                'source_inputs': {name: metadata(blob) for name, blob in snapshots.items()},
                'address_analysis': report['address_analysis'], 'real_overlay': report['real_overlay'],
                'required_before_execution': REQUIRED_BEFORE_EXECUTION,
                'board_runtime_proof_required': BOARD_RUNTIME_PROOF_REQUIRED}
    write_new(output / 'manifest.json', json_bytes(manifest))
    inventory = {str(path.relative_to(output)): metadata(read_ordinary(path))
                 for path in sorted(output.rglob('*')) if path.is_file()}
    receipt = {'schema': 1, 'status': image_inputs['mode'], 'files': inventory,
               'board_tested': False, 'formal_flash_ready': False, 'freeze_scope': 'ALL_FILES_BEFORE_RECEIPT'}
    write_new(output / 'receipt.json', json_bytes(receipt))
    return manifest


def audit_directory(candidate, image_inputs):
    path = Path(candidate).absolute()
    require(path == path.resolve() and path.is_relative_to(HERE / 'build'), 'Own ordinary candidate directory required')
    receipt = unique_json(read_ordinary(path / 'receipt.json', 4 * 1024 * 1024))
    names = {str(item.relative_to(path)) for item in path.rglob('*') if item.is_file() or item.is_symlink()}
    require(names == set(receipt['files']) | {'receipt.json'}, 'Candidate freeze inventory set changed')
    require(receipt['status'] == image_inputs['mode'] and receipt['board_tested'] is False and
            receipt['formal_flash_ready'] is False, 'Candidate receipt mode/boundary')
    for name, info in receipt['files'].items():
        require(str(PurePosixPath(name)) == name and not name.startswith('/') and
                all(part not in ('', '.', '..') for part in name.split('/')), 'Unsafe freeze relative name')
        require(metadata(read_ordinary(path / name)) == info, 'Candidate frozen file changed: ' + name)
    data = read_ordinary(path / 'boot-padded.img')
    report = inspect_candidate(data, image_inputs)
    manifest = unique_json(read_ordinary(path / 'manifest.json', 4 * 1024 * 1024))
    require(type(manifest.get('schema')) is int and manifest['schema'] == 1 and
            all(manifest.get(name) is False for name in ('board_tested', 'deployed', 'flash_authorized',
                                                        'saveenv', 'formal_flash_ready')),
            'Candidate manifest offline-only boundary')
    require(manifest.get('native_pid1_old_rcu_image_check_is_new_image_identity') is False,
            'Candidate manifest old RCU check is not new Image identity')
    require(manifest.get('rootfs_board_path') == '/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4',
            'Candidate manifest rootfs cache path')
    require(manifest.get('cmdline') == CMDLINE and manifest.get('official_commit') == OFFICIAL_COMMIT and
            manifest.get('official_functions') == ['write_header', 'write_data'],
            'Candidate manifest cmdline/official functions')
    require(manifest.get('required_before_execution') == REQUIRED_BEFORE_EXECUTION and
            manifest.get('board_runtime_proof_required') == BOARD_RUNTIME_PROOF_REQUIRED, 'Exact fresh execution and runtime proof requirements')
    fixed = fixed_inputs()
    require(manifest.get('original') == {'path': FIXED['original'][0], **metadata(fixed['original'])} and
            manifest.get('inputs') == {name: {'path': fields[0], **metadata(fixed[name])}
                                      for name, fields in FIXED.items() if name != 'original'},
            'Candidate manifest fixed input binding')
    if image_inputs['mode'] == 'RAM_ONLY_NOT_FLASH_READY':
        for name, blob in image_inputs['runtime_blobs'].items():
            require(read_ordinary(path / 'runtime' / name) == blob, 'Runtime sidecar content binding: ' + name)
        require(read_ordinary(path / 'runtime/SHA256SUMS') == runtime_sums(image_inputs['runtime_blobs']), 'Runtime exact checksum list')
    expected_image = {key: value for key, value in image_inputs.items() if key not in ('kernel', 'runtime_blobs')}
    require(manifest['status'] == image_inputs['mode'] and manifest['image_input'] == expected_image and
            manifest['kernel'] == metadata(image_inputs['kernel']), 'Candidate manifest input binding')
    require(manifest['artifacts']['boot-padded.img'] == metadata(data) and
            manifest['artifacts']['boot-raw.img'] == metadata(data[:report['raw_bytes']]), 'Candidate artifact binding')
    require(read_ordinary(path / 'boot-raw.img') == data[:report['raw_bytes']], 'Raw/padded package binding')
    for component in report['components']:
        name = component['name']
        blob = data[component['offset']:component['offset'] + component['bytes']]
        require(read_ordinary(path / 'components' / name) == blob and manifest['components'][name] == metadata(blob),
                'Candidate components binding: ' + name)
    require(manifest['address_analysis'] == report['address_analysis'] and manifest['real_overlay'] == report['real_overlay'],
            'Candidate semantic/address manifest binding')
    _, checked = dependencies()
    expected_sources = {name: metadata(blob) for name, blob in checked.items()}
    for name, blob in checked.items():
        require(read_ordinary(path / 'source-inputs' / name) == blob, 'Locked dependency snapshot binding')
    for name in ('audio-package-v5.py',):
        relative = str((HERE / name).relative_to(ROOT))
        blob = read_ordinary(HERE / name)
        expected_sources[relative] = metadata(blob)
        require(read_ordinary(path / 'source-inputs' / relative) == blob, 'Current builder/auditor snapshot binding')
    require(manifest.get('source_inputs') == expected_sources, 'Candidate manifest source snapshot metadata')
    report['candidate_manifest'] = metadata(read_ordinary(path / 'manifest.json'))
    report['candidate_receipt'] = metadata(read_ordinary(path / 'receipt.json'))
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'audit'])
    parser.add_argument('--review-gate', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--candidate')
    args = parser.parse_args()
    require((args.action == 'audit') == bool(args.candidate), 'Only audit requires candidate')
    inputs = production_inputs(args.review_gate)
    if args.action == 'build':
        manifest = construct_package(args.out, inputs)
        print(json.dumps({'status': manifest['status'], 'artifacts': manifest['artifacts'],
                          'board_tested': False, 'formal_flash_ready': False}, indent=2))
    else:
        report = audit_directory(args.candidate, inputs)
        output = fresh_directory(args.out)
        write_new(output / 'audit.json', json_bytes(report))
        write_new(output / 'receipt.json', json_bytes({
            'mode': 'PRODUCTION_AUDIO_RAM_OFFLINE_AUDIT_ONLY',
            'auditor_sha256': metadata(Path(__file__).read_bytes())['sha256'],
            'audit': metadata(read_ordinary(output / 'audit.json')), 'image_manifest': inputs['image_manifest'],
            'review_gate': inputs['review_gate'], 'board_tested': False, 'formal_flash_ready': False}))
        print(json.dumps({'status': 'PRODUCTION_AUDIO_RAM_OFFLINE_VERIFIED', 'package': report['package'],
                          'raw_bytes': report['raw_bytes'], 'board_tested': False, 'formal_flash_ready': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit('AUDIO_PACKAGE_' + ('AUDIT' if 'audit' in __import__('sys').argv else 'BUILD') + '_REJECTED: ' + str(error))
