#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the frozen codec in a private copy of a completed integration-v4 ABI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4'
ABI = ROOT / '.deps/kernel/aiot-3568pq-audio-v4'
IMAGE = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/integration-v4'
ROOT_ABI = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/root-image-v4-abi-v1'
ROOT_ABI_RECEIPT_SHA = '2f25e37f2a30732ebd378c2874f1d7a3c3d37f19b7fe1d6486646bac61998e58'
ROOT_ABI_INVENTORY_SHA = 'bf3766426c2eb869442dc2703f6321eaad6143ebeaf63dad279c72eaf0f3e2a3'
CONFIG_SHA = '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'
RELEASE = '5.10.160-rt89-g9f9e9d18574d-dirty'
VERMAGIC = RELEASE + ' SMP preempt_rt mod_unload aarch64'
CODEC_SHA = '72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64'
HEADER_SHA = '370f2c9451d0e871b627c7b9a9b90cc24e486c49cebe29c068d5b692f7802449'
PREPARED_INPUTS_SHA = '6ef8c70f6b47acbf497b9b6eedbf0dde3a9ee6876e869832b24761238d0b6d0a'
COPY_DIRS = ['include', 'arch/arm64/include', 'scripts']
COPY_FILES = ['.config', 'Module.symvers', 'vmlinux.symvers', 'Makefile']
SOURCE_SELECTIONS = ['include', 'arch/arm64/include', 'scripts', 'Makefile', 'arch/arm64/Makefile',
                     'sound/soc/codecs/Makefile', 'sound/soc/codecs/Kconfig',
                     'sound/soc/codecs/rk817_codec.c', 'sound/soc/codecs/rk817_codec.h']
SDK_LINKS = {
    'include/dt-bindings/clock/qcom,dispcc-sm8150.h': ('qcom,dispcc-sm8250.h',
        'include/dt-bindings/clock/qcom,dispcc-sm8250.h', '8350d0b570b4dd399de4c165feab070bc7d482e1db289799ef4ff2cca97abf3d'),
    'include/dt-bindings/input/linux-event-codes.h': ('../../uapi/linux/input-event-codes.h',
        'include/uapi/linux/input-event-codes.h', '86ee5494ecb443604f65faa86937a787ff979559ffa53247b2c6b1aa52791514'),
    'scripts/dummy-tools/nm': ('ld', 'scripts/dummy-tools/ld', '0ce50ae7c6a895e812f1ce246ccb88d3eef034ff87cc0908618de2b555ad3aee'),
    'scripts/dummy-tools/objcopy': ('ld', 'scripts/dummy-tools/ld', '0ce50ae7c6a895e812f1ce246ccb88d3eef034ff87cc0908618de2b555ad3aee'),
}
DTC_DIRECTORY_LINKS = {'scripts/dtc/include-prefixes/' + name: ('../../../' + target, target)
    for name, target in [('arc', 'arch/arc/boot/dts'), ('arm', 'arch/arm/boot/dts'),
        ('arm64', 'arch/arm64/boot/dts'), ('c6x', 'arch/c6x/boot/dts'), ('dt-bindings', 'include/dt-bindings'),
        ('h8300', 'arch/h8300/boot/dts'), ('microblaze', 'arch/microblaze/boot/dts'),
        ('mips', 'arch/mips/boot/dts'), ('nios2', 'arch/nios2/boot/dts'), ('openrisc', 'arch/openrisc/boot/dts'),
        ('powerpc', 'arch/powerpc/boot/dts'), ('sh', 'arch/sh/boot/dts'), ('xtensa', 'arch/xtensa/boot/dts')]}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def insert_lock(locks, path, digest):
    require(path not in locks or locks[path] == digest, 'Conflicting mandatory input lock: ' + str(path))
    locks[path] = digest


def ordinary_directory(path):
    require(path.is_relative_to(ROOT) and '..' not in path.parts, 'Directory escaped repository')
    p = path
    while True:
        require(stat.S_ISDIR(p.lstat().st_mode), 'Nonordinary directory ancestor: ' + str(p))
        if p == ROOT:
            break
        p = p.parent


def ordinary(path):
    require(path.is_relative_to(ROOT) and '..' not in path.parts, 'File escaped repository')
    ordinary_directory(path.parent)
    require(stat.S_ISREG(path.lstat().st_mode), 'Nonordinary file: ' + str(path))
    return path


def fresh(path):
    require(path.is_relative_to(HERE) and '..' not in path.parts, 'Output escaped ownership')
    ordinary_directory(path.parent)
    require(not path.exists() and not path.is_symlink(), 'Fresh output required: ' + str(path))


def inspect_DTC_prefix_link(tree, relative):
    require(relative in DTC_DIRECTORY_LINKS, 'Unknown typed DTC prefix link')
    p = tree / relative
    ordinary_directory(p.parent)
    require(stat.S_ISLNK(p.lstat().st_mode), 'DTC prefix must be a link')
    target, resolved = DTC_DIRECTORY_LINKS[relative]
    require(str(p.readlink()) == target and p.resolve().is_relative_to(tree) and
            p.resolve().relative_to(tree).as_posix() == resolved, 'DTC prefix directory target changed')
    ordinary_directory(tree / resolved)
    original_tree = ROOT / 'third_party/linux-rk3588'
    original = original_tree / relative
    ordinary_directory(original.parent)
    require(stat.S_ISLNK(original.lstat().st_mode) and str(original.readlink()) == target and
            original.resolve().is_relative_to(original_tree) and
            original.resolve().relative_to(original_tree).as_posix() == resolved, 'DTC prefix differs from original SDK link')
    ordinary_directory(original_tree / resolved)
    return {'link_text': target, 'resolved_relative': resolved,
            'target_kind': 'ordinary_directory', 'target_contents_traversed': False,
            'original_SDK_link_equal': True, 'original_SDK_target_ordinary_directory': True,
            'link_text_sha256': hashlib.sha256(target.encode()).hexdigest()}


def inventory(tree, selections, known_sdk_links=False):
    ordinary_directory(tree)
    regular, metadata, links, dirs = {}, {}, {}, set()
    for name in selections:
        top = tree / name
        mode = top.lstat().st_mode
        candidates = [top, *sorted(top.rglob('*'))] if stat.S_ISDIR(mode) else [top]
        for p in candidates:
            relative = p.relative_to(tree).as_posix()
            mode = p.lstat().st_mode
            if stat.S_ISDIR(mode):
                ordinary_directory(p)
                dirs.add(relative)
            elif stat.S_ISREG(mode):
                ordinary(p)
                regular[relative] = sha(p)
                metadata[relative] = {'sha256': regular[relative], 'bytes': p.stat().st_size,
                                      'mode': stat.S_IMODE(mode)}
            elif stat.S_ISLNK(mode):
                require(known_sdk_links and relative in set(SDK_LINKS) | set(DTC_DIRECTORY_LINKS), 'Unknown input link: ' + relative)
                ordinary_directory(p.parent)
                if relative in DTC_DIRECTORY_LINKS:
                    links[relative] = inspect_DTC_prefix_link(tree, relative)
                    continue
                target, resolved, digest = SDK_LINKS[relative]
                require(str(p.readlink()) == target and p.resolve().is_relative_to(tree) and
                        p.resolve().relative_to(tree).as_posix() == resolved, 'SDK link target changed')
                ordinary(tree / resolved)
                require(sha(tree / resolved) == digest, 'SDK link resolved bytes changed')
                links[relative] = {'link_text': target, 'resolved_relative': resolved, 'resolved_sha256': digest,
                                   'target_kind': 'ordinary_file',
                                   'link_text_sha256': hashlib.sha256(target.encode()).hexdigest()}
            else:
                raise ValueError('Nonordinary inventory member: ' + relative)
    if known_sdk_links:
        require(set(links) == set(SDK_LINKS) | set(DTC_DIRECTORY_LINKS), 'Incomplete known SDK link inventory')
    return {'regular_files_sha256': regular, 'regular_files_metadata': metadata, 'regular_file_count': len(regular),
            'known_SDK_internal_links': links, 'SDK_internal_link_count': len(links),
            'ordinary_directories': sorted(dirs), 'ordinary_ancestry_checked': True,
            'links_not_counted_as_regular_files': True}


def source_matches_image_inventory(selected, tracked, selections):
    require(len(tracked) == 89423, 'Complete actual Image source inventory required')
    expected_keys = {name for name in tracked if any(name == prefix or name.startswith(prefix + '/') for prefix in selections)}
    regular_keys = set(selected['regular_files_metadata'])
    link_keys = set(selected['known_SDK_internal_links'])
    require(not regular_keys.intersection(link_keys) and expected_keys == regular_keys | link_keys,
            'Source finite selection missing/extra paths against completed Image')
    for name, item in selected['regular_files_metadata'].items():
        actual = {'sha256': item['sha256'], 'bytes': item['bytes'],
                  'mode': '100755' if item['mode'] & 0o111 else '100644'}
        require(actual == tracked.get(name), 'Source selection differs from completed Image: ' + name)
    for name, item in selected['known_SDK_internal_links'].items():
        actual = {'sha256': item['link_text_sha256'], 'bytes': len(item['link_text'].encode()), 'mode': '120000'}
        require(actual == tracked.get(name), 'SDK link differs from completed Image: ' + name)


def generated_matches_root_snapshot(selected, root_inventory):
    require(set(root_inventory['selections']) == set(COPY_DIRS + COPY_FILES), 'Unexpected root generated selections')
    require(selected['SDK_internal_link_count'] == 0 and selected['regular_files_metadata'] == root_inventory['files'],
            'Actual generated ABI differs from root completed-Image snapshot')


def symbols(path):
    result = {}
    for line in ordinary(path).read_text().splitlines():
        fields = line.split()
        require(len(fields) in {4, 5}, 'Malformed symvers record')
        crc, name, provider, export_type = fields[:4]
        require(re.fullmatch(r'0x[0-9a-fA-F]{8}', crc) and name not in result, 'Malformed/duplicate symvers symbol')
        result[name] = {'crc': crc, 'provider': provider, 'export_type': export_type,
                        'namespace': fields[4] if len(fields) == 5 else ''}
    return result


def elf_sections(path):
    data = ordinary(path).read_bytes()
    require(len(data) >= 64 and data[:6] == b'\x7fELF\x02\x01', 'Need ELF64 little-endian')
    header = struct.unpack_from('<HHIQQQIHHHHHH', data, 16)
    require(header[0:3] == (1, 183, 1) and header[7] == 64, 'Need AArch64 ET_REL ELF v1')
    shoff, shentsize, shnum, shstr = header[5], header[10], header[11], header[12]
    require(shentsize == 64 and 0 < shstr < shnum and shoff + shnum * 64 <= len(data), 'ELF section table bounds')
    tables = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * 64) for i in range(shnum)]
    strings = tables[shstr]
    require(strings[4] + strings[5] <= len(data), 'ELF string table bounds')
    names = data[strings[4]:strings[4] + strings[5]]
    result = {}
    for entry in tables:
        require(entry[0] < len(names), 'ELF section name bounds')
        end = names.find(b'\0', entry[0])
        require(end >= 0, 'ELF section name termination')
        name = names[entry[0]:end].decode('ascii')
        if entry[1] != 8:
            require(entry[4] + entry[5] <= len(data), 'ELF section data bounds')
        if name:
            require(name not in result, 'Duplicate ELF named section')
            result[name] = {'type': entry[1], 'offset': entry[4], 'bytes': entry[5]}
    return data, result


def record_run(out, steps, label, argv, env=None):
    stdout = out / (label + '.stdout')
    stderr = out / (label + '.stderr')
    with stdout.open('wb') as output:
        with stderr.open('wb') as error:
            process = subprocess.run(argv, env=env, stdout=output, stderr=error)
    item = {'label': label, 'argv': [str(x) for x in argv], 'exit': process.returncode,
            'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr)}
    steps.append(item)
    write_json(out / (label + '.command.json'), item)
    require(process.returncode == 0, 'Command failed; real evidence retained: ' + label)
    return stdout.read_text()


def audit_module(module, out, steps, exports, vmlinux_exports):
    initial = sha(module)
    data, sections = elf_sections(module)
    require('__versions' not in sections and '.modinfo' in sections, 'MODVERSIONS=n must have no __versions')
    require('.interp' not in sections and '.dynamic' not in sections, 'Module has userspace dynamic sections')
    raw = sections['.modinfo']
    metadata_bytes = data[raw['offset']:raw['offset'] + raw['bytes']]
    (out / 'module.modinfo').write_bytes(metadata_bytes)
    metadata = {}
    for entry in metadata_bytes.split(b'\0'):
        if b'=' in entry:
            key, value = entry.decode().split('=', 1)
            metadata.setdefault(key, []).append(value)
    require(metadata.get('vermagic') == [VERMAGIC], 'Wrong actual vermagic')
    require(metadata.get('license') == ['GPL v2'] and metadata.get('name') == ['snd_soc_rk817'], 'Wrong actual module identity')
    require(metadata.get('depends') == [''] and any('rockchip,rk817-codec' in x for x in metadata.get('alias', [])),
            'Wrong module dependency/OF alias')
    header = record_run(out, steps, 'module-readelf', ['aarch64-linux-gnu-readelf', '-W', '-h', '-l', '-d', '-S', str(module)])
    require('INTERP' not in header and 'NEEDED' not in header, 'Dynamic ELF dependency')
    undefined = record_run(out, steps, 'module-undefined', ['aarch64-linux-gnu-nm', '--undefined-only', str(module)])
    imports = {}
    for line in undefined.splitlines():
        fields = line.split()
        require(len(fields) == 2 and fields[0] == 'U', 'Unreviewed weak/other import')
        name = fields[1]
        item = exports.get(name)
        require(item is not None and item == vmlinux_exports.get(name) and item['provider'] == 'vmlinux' and
                not item['namespace'], 'Import is not an exact actual Image built-in: ' + name)
        imports[name] = item
    required = {'regmap_read', 'snd_soc_component_write', 'snd_soc_component_update_bits',
                'snd_soc_add_component_controls', 'devm_snd_soc_register_component', 'clk_prepare', 'clk_enable'}
    forbidden = {'snd_soc_component_exit_regmap', '__devm_regmap_init_i2c', '__regmap_init_i2c',
                 'regmap_exit', 'devm_add_action'}
    require(required <= imports.keys() and not forbidden.intersection(imports), 'Frozen real PMIC map-borrow contract changed')
    defined = record_run(out, steps, 'module-defined', ['aarch64-linux-gnu-nm', '--defined-only', str(module)])
    require(' init_module' in defined and ' cleanup_module' in defined, 'Missing real module lifecycle entry')
    require(initial == sha(module), 'Audit mutated module')
    return {'sha256': initial, 'bytes': len(data), 'elf': 'ELF64 LE AArch64 ET_REL',
            'metadata': metadata, 'imports': imports, 'imports_from_actual_Module_and_vmlinux_symvers': True,
            'imports_resolved': True, 'elf_has_interp': False, 'elf_has_needed': False,
            'defined_symbols_recorded': True,
            'MODVERSIONS_enabled': False, '__versions_section_present': False,
            'CRC_runtime_enforcement_claimed': False, 'sections': sections,
            'vermagic_exact': True, 'unload_safe': False, 'board_tested': False}


def validate_record(record):
    require(type(record.get('build_exit_code')) is int and record['build_exit_code'] == 0 and
            record.get('kernel_release') == RELEASE, 'Completed correct Image required')
    require(record.get('config_sha256') == CONFIG_SHA and record.get('codec_source_sha256') == CODEC_SHA,
            'Image frozen config/codec changed')
    require(record.get('source') == SOURCE.relative_to(ROOT).as_posix() and
            record.get('build') == ABI.relative_to(ROOT).as_posix(), 'Image source/build path changed')
    require(record.get('compressed_audio_enabled') is False and record.get('battery_algorithm_enabled') is False and
            record.get('duplex_START_gates_relaxed') is False, 'Unreviewed Image profile')
    for key in ['image_sha256', 'module_symvers_sha256', 'vmlinux_symvers_sha256',
                'integrated_source_inventory_sha256', 'builder_sha256']:
        require(isinstance(record.get(key), str) and re.fullmatch('[0-9a-f]{64}', record[key]), 'Missing Image hash ' + key)


def run_build(args, out, steps):
    frozen_builder_sha = sha(ordinary(out / 'builder-snapshot.py'))
    require(sha(ordinary(Path(__file__))) == frozen_builder_sha, 'Executing builder differs from snapshot')
    record = json.loads(ordinary(IMAGE / 'manifest.json').read_text())
    validate_record(record)
    require(sha(IMAGE / 'manifest.json') == args.image_manifest_sha256 and
            record['image_sha256'] == args.image_sha256, 'Root-notified Image binding changed')
    locks = {IMAGE / 'manifest.json': args.image_manifest_sha256,
             IMAGE / 'Image': args.image_sha256, ABI / 'arch/arm64/boot/Image': args.image_sha256,
             ABI / '.config': CONFIG_SHA, IMAGE / 'kernel.config': CONFIG_SHA,
             ABI / 'Module.symvers': record['module_symvers_sha256'],
             ABI / 'vmlinux.symvers': record['vmlinux_symvers_sha256'],
             IMAGE / 'Module.symvers': record['module_symvers_sha256'],
             IMAGE / 'vmlinux.symvers': record['vmlinux_symvers_sha256'],
             IMAGE / 'integrated-source-inventory.json': record['integrated_source_inventory_sha256'],
             ROOT_ABI / 'receipt.json': ROOT_ABI_RECEIPT_SHA,
             ROOT_ABI / 'inventory.json': ROOT_ABI_INVENTORY_SHA,
             ROOT / 'outputs/rk3568-audio-runtime-20261005/build-audio-image-v4.py': record['builder_sha256'],
             SOURCE / 'sound/soc/codecs/rk817_codec.c': CODEC_SHA,
             SOURCE / 'sound/soc/codecs/rk817_codec.h': HEADER_SHA,
             HERE / 'source-v1/rk817_codec.c': CODEC_SHA, HERE / 'source-v1/rk817_codec.h': HEADER_SHA}
    preparation_path = ordinary(HERE / 'prepared-inputs-v1.json')
    require(sha(preparation_path) == PREPARED_INPUTS_SHA, 'Frozen exact prepared manifest changed')
    preparation = json.loads(preparation_path.read_text())
    require(set(preparation['inputs']) == {'frozen_codec', 'frozen_header', 'original_codec', 'original_header',
                                         'reference_builder_v3', 'reference_audit'}, 'Exact six prepared items required')
    locks[preparation_path] = PREPARED_INPUTS_SHA
    for item in preparation['inputs'].values():
        insert_lock(locks, ROOT / item['source'], item['sha256'])
        insert_lock(locks, HERE / item['snapshot'], item['sha256'])
    for path, digest in locks.items():
        require(sha(ordinary(path)) == digest, 'Image/source lock changed: ' + str(path))
    config = (ABI / '.config').read_text().splitlines()
    required = ['CONFIG_MODULES=y', 'CONFIG_PREEMPT_RT=y', 'CONFIG_SMP=y', 'CONFIG_MODULE_UNLOAD=y',
                'CONFIG_ARM64=y', '# CONFIG_MODVERSIONS is not set', '# CONFIG_SND_SOC_RK817 is not set',
                'CONFIG_REGMAP_I2C=y', 'CONFIG_SND_SOC=y']
    require(all(x in config for x in required) and not any(x.startswith('CONFIG_SND_SOC_COMPRESS=') for x in config),
            'Actual Image configuration mismatch')
    require((ordinary(ABI / 'include/config/kernel.release')).read_text().strip() == RELEASE and
            (ordinary(ABI / 'include/generated/utsrelease.h')).read_text().strip() == '#define UTS_RELEASE "' + RELEASE + '"',
            'Actual generated release mismatch')
    auto = ordinary(ABI / 'include/generated/autoconf.h').read_text()
    require('#define CONFIG_MODVERSIONS' not in auto and '#define CONFIG_SND_SOC_RK817' not in auto, 'Generated config mismatch')
    before_abi = inventory(ABI, COPY_DIRS + COPY_FILES)
    source_selections = SOURCE_SELECTIONS
    before_source = inventory(SOURCE, source_selections, True)
    tracked_image_source = json.loads((IMAGE / 'integrated-source-inventory.json').read_text())
    source_matches_image_inventory(before_source, tracked_image_source, source_selections)
    root_abi_receipt = json.loads((ROOT_ABI / 'receipt.json').read_text())
    require(root_abi_receipt['root_current_generated_ABI_snapshot_completed'] and
            root_abi_receipt['image_manifest_sha256'] == args.image_manifest_sha256 and
            root_abi_receipt['image_sha256'] == args.image_sha256 and
            root_abi_receipt['inventory_sha256'] == ROOT_ABI_INVENTORY_SHA and
            root_abi_receipt['actual_BUILD_selection_before_after_equal'] and
            root_abi_receipt['copied_bytes_sizes_modes_equal'] and
            not root_abi_receipt['generated_inventory_was_signed_at_Image_compile_time'], 'Root ABI identity/scope mismatch')
    root_abi_inventory = json.loads((ROOT_ABI / 'inventory.json').read_text())
    generated_matches_root_snapshot(before_abi, root_abi_inventory)
    root_snapshot = inventory(ROOT_ABI / 'snapshot', COPY_DIRS + COPY_FILES)
    generated_matches_root_snapshot(root_snapshot, root_abi_inventory)
    for name in ['receipt.json', 'inventory.json']:
        shutil.copy2(ROOT_ABI / name, out / ('root-ABI-' + name))
    write_json(out / 'before-ABI.json', before_abi)
    write_json(out / 'before-source-headers-scripts.json', before_source)
    write_json(out / 'locks.json', {p.relative_to(ROOT).as_posix(): digest for p, digest in locks.items()})
    for name in ['manifest.json', 'Module.symvers', 'vmlinux.symvers', 'kernel.config', 'integrated-source-inventory.json']:
        shutil.copy2(IMAGE / name, out / ('Image-' + name))
    shadow = out / 'kernel-abi'
    shadow.mkdir()
    for name in COPY_DIRS:
        shutil.copytree(ABI / name, shadow / name)
    for name in COPY_FILES:
        shutil.copy2(ABI / name, shadow / name)
    require(inventory(shadow, COPY_DIRS + COPY_FILES) == before_abi, 'Copied actual generated ABI differs')
    generated_matches_root_snapshot(inventory(shadow, COPY_DIRS + COPY_FILES), root_abi_inventory)
    modules = out / 'modules'
    modules.mkdir()
    for name in ['rk817_codec.c', 'rk817_codec.h']:
        shutil.copy2(HERE / 'source-v1' / name, modules / name)
    for name, expected in [('rk817_codec.c', CODEC_SHA), ('rk817_codec.h', HEADER_SHA)]:
        require(sha(ordinary(modules / name)) == expected, 'Actual module translation input changed')
        insert_lock(locks, modules / name, expected)
    (modules / 'Makefile').write_text('obj-m += snd-soc-rk817.o\nsnd-soc-rk817-objs := rk817_codec.o\n')
    paths = [SOURCE / 'arch/arm64/include', shadow / 'arch/arm64/include/generated', SOURCE / 'include', shadow / 'include',
             SOURCE / 'arch/arm64/include/uapi', shadow / 'arch/arm64/include/generated/uapi',
             SOURCE / 'include/uapi', shadow / 'include/generated/uapi']
    includes = ' '.join('-I' + str(p) for p in paths) + ' -include ' + str(SOURCE / 'include/linux/kconfig.h')
    argv = ['make', '-C', str(shadow), 'M=' + str(modules), 'ARCH=arm64',
            'CROSS_COMPILE=aarch64-linux-gnu-', 'LINUXINCLUDE=' + includes, 'V=1', '-j2', 'modules']
    env = dict(os.environ)
    env['PATH'] = str(ROOT / '.deps/host-tools/bin') + ':' + env['PATH']
    compiler = record_run(out, steps, 'compiler-version', ['aarch64-linux-gnu-gcc', '--version'], env).splitlines()[0]
    require(compiler == record['compiler'] == 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0', 'Actual Image compiler differs')
    # Inputs are already saved before invoking the only actual build command.
    build_error = None
    try:
        record_run(out, steps, 'build', argv, env)
    except Exception as error:
        build_error = error
    after_abi = inventory(ABI, COPY_DIRS + COPY_FILES)
    after_source = inventory(SOURCE, source_selections, True)
    write_json(out / 'after-ABI.json', after_abi)
    write_json(out / 'after-source-headers-scripts.json', after_source)
    shadow_after = inventory(shadow, COPY_DIRS + COPY_FILES)
    write_json(out / 'after-shadow-ABI.json', shadow_after)
    generated_matches_root_snapshot(shadow_after, root_abi_inventory)
    require(before_abi == after_abi and before_source == after_source, 'Original Image generated ABI/source changed')
    generated_matches_root_snapshot(after_abi, root_abi_inventory)
    source_matches_image_inventory(after_source, tracked_image_source, source_selections)
    for path, digest in locks.items():
        require(sha(ordinary(path)) == digest, 'Locked input changed after build')
    if build_error:
        raise build_error
    primary = ordinary(modules / '.rk817_codec.o.cmd').read_text().splitlines()[0]
    require('-DMODULE' in primary and str(modules / 'rk817_codec.c') in primary, 'Frozen source did not participate in module Kbuild')
    require(not symbols(modules / 'Module.symvers'), 'Unexpected codec exports')
    actual_module = audit_module(modules / 'snd-soc-rk817.ko', out, steps,
                                 symbols(ABI / 'Module.symvers'), symbols(ABI / 'vmlinux.symvers'))
    # Audit tools are read-only; repeat finite input checks after them as well.
    require(inventory(ABI, COPY_DIRS + COPY_FILES) == before_abi and
            inventory(SOURCE, source_selections, True) == before_source, 'Audit changed Image input')
    source_matches_image_inventory(inventory(SOURCE, source_selections, True), tracked_image_source, source_selections)
    generated_matches_root_snapshot(inventory(ABI, COPY_DIRS + COPY_FILES), root_abi_inventory)
    generated_matches_root_snapshot(inventory(ROOT_ABI / 'snapshot', COPY_DIRS + COPY_FILES), root_abi_inventory)
    generated_matches_root_snapshot(inventory(shadow, COPY_DIRS + COPY_FILES), root_abi_inventory)
    for path, digest in locks.items():
        require(sha(ordinary(path)) == digest, 'Final locked input changed')
    require(sha(ordinary(Path(__file__))) == sha(out / 'builder-snapshot.py') == frozen_builder_sha,
            'Builder changed before completion')
    return {'image_sha256': args.image_sha256, 'image_manifest_sha256': args.image_manifest_sha256,
            'actual_module': actual_module, 'module': actual_module,
            'source_sha256': CODEC_SHA, 'header_sha256': HEADER_SHA,
            'module_symvers_sha256': record['module_symvers_sha256'],
            'vmlinux_symvers_sha256': record['vmlinux_symvers_sha256'],
            'abi_inventory': before_abi['regular_files_sha256'], 'abi_unchanged': True,
            'abi_inventory_scope': 'complete generated include/arch include/scripts plus config/symvers/Makefile',
            'audit_source_sha256': sha(Path(__file__)), 'audit_source': Path(__file__).relative_to(ROOT).as_posix(),
            'audit_embedded_in_builder': True,
            'root_generated_ABI_receipt_sha256': ROOT_ABI_RECEIPT_SHA,
            'root_generated_ABI_inventory_sha256': ROOT_ABI_INVENTORY_SHA,
            'root_generated_ABI_scope': root_abi_receipt['scope'],
            'generated_inventory_was_signed_at_Image_compile_time': False,
            'actual_generated_ABI_selections': COPY_DIRS + COPY_FILES,
            'actual_generated_ABI_regular_files': before_abi['regular_file_count'],
            'actual_compiled_codec_source_sha256': sha(modules / 'rk817_codec.c'),
            'actual_compiled_codec_header_sha256': sha(modules / 'rk817_codec.h'),
            'prepared_inputs_manifest_sha256': PREPARED_INPUTS_SHA,
            'source_selection_matched_complete_Image_inventory': True,
            'source_selection_exact_keys_matched': True, 'actual_source_selections': SOURCE_SELECTIONS,
            'source_known_SDK_links': before_source['known_SDK_internal_links'],
            'actual_Module_symvers_sha256': record['module_symvers_sha256'],
            'actual_vmlinux_symvers_sha256': record['vmlinux_symvers_sha256'], 'actual_config_sha256': CONFIG_SHA,
            'ABI_inventory_sha256': sha(out / 'before-ABI.json'), 'source_inventory_sha256': sha(out / 'before-source-headers-scripts.json'),
            'original_ABI_and_finite_source_unchanged': True, 'compiler': compiler, 'build_argv': argv,
            'actual_primary_Kbuild_command_sha256': sha(modules / '.rk817_codec.o.cmd'),
            'codec_exports': {}, 'module_selection': 'External obj-m; actual CONFIG_SND_SOC_RK817=n unchanged',
            'kernel_release': RELEASE, 'modversions': False,
            'board_tested': False, 'loaded': False, 'unload_tested': False, 'deployed': False,
            'full_duplex_passed': False, 'accepted_for_board': False,
            'limitations': ['Import closure/header binding does not prove board loading or module unload safety',
                            'MODVERSIONS=n: no encoded CRC comparison/enforcement claimed',
                            'No control/PCM/DAPM/PLL/suspend/shared-DAI/hardware tests performed here']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-sha256', required=True)
    parser.add_argument('--image-manifest-sha256', required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    require(re.fullmatch('v[1-9][0-9]*', args.attempt), 'Fresh vN attempt required')
    require(all(re.fullmatch('[0-9a-f]{64}', x) for x in [args.image_sha256, args.image_manifest_sha256]), 'Exact root-notified Image hashes required')
    out = HERE / ('build-' + args.attempt)
    fresh(out)
    out.mkdir()
    shutil.copy2(Path(__file__), out / 'builder-snapshot.py')
    write_json(out / 'invocation.json', {'argv': list(os.sys.argv), 'image_sha256': args.image_sha256,
                                        'image_manifest_sha256': args.image_manifest_sha256, 'builder_sha256': sha(Path(__file__))})
    steps = []
    try:
        record = run_build(args, out, steps)
        record.update({'status': 'ACTUAL_COMPLETED_IMAGE_CODEC_ABI_VERIFIED', 'steps': steps,
                       'builder_sha256': sha(out / 'builder-snapshot.py'), 'build_exit_code': 0})
        write_json(out / 'manifest.json', record)
        print(json.dumps({'module_sha256': record['actual_module']['sha256'],
                          'imports': len(record['actual_module']['imports']), 'board_tested': False}))
    except Exception:
        (out / 'failure.traceback').write_text(traceback.format_exc())
        write_json(out / 'failure.json', {'status': 'FAILED_REAL_ATTEMPT_EVIDENCE_PRESERVED', 'steps': steps,
                                        'builder_sha256': sha(out / 'builder-snapshot.py'),
                                        'Image_or_ABI_success_claimed': False, 'board_tested': False})
        raise


if __name__ == '__main__':
    main()
