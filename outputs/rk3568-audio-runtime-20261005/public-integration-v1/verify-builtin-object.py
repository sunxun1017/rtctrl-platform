#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile the real built-in target from public replay and compare old objects read-only."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('public_verify', HERE / 'verify-public-series.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
ACTUAL_OBJECT = verify.ABI / 'sound/soc/rockchip/rockchip_i2s_tdm.o'
ACTUAL_COMMAND = verify.ABI / 'sound/soc/rockchip/.rockchip_i2s_tdm.o.cmd'
ACTUAL_OBJECT_SHA = 'f1e0b2853592ec3b2eac590e9f35c5e85677fb408a0c859f1a62a420f2a8e717'


def sections(path):
    """Read the ELF64 section directory; GNU readelf separately records its view."""
    data = path.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', data, 16) != (1, 183):
        raise ValueError('Need ordinary ELF64 LE AArch64 ET_REL')
    start = struct.unpack_from('<Q', data, 40)[0]
    entry_size, count, names_index = struct.unpack_from('<HHH', data, 58)
    if entry_size != 64 or not count or names_index >= count:
        raise ValueError('Unexpected ELF section directory')
    rows = [struct.unpack_from('<IIQQQQIIQQ', data, start + i * entry_size) for i in range(count)]
    name_row = rows[names_index]
    names = data[name_row[4]:name_row[4] + name_row[5]]
    result = {}
    for row in rows[1:]:
        name_end = names.index(b'\0', row[0])
        name = names[row[0]:name_end].decode()
        body = b'' if row[1] == 8 else data[row[4]:row[4] + row[5]]
        result[name] = {'type': row[1], 'flags': row[2], 'bytes': row[5],
                        'body_sha256': hashlib.sha256(body).hexdigest()}
    return result


def compare(out, label, left, right):
    left_sections, right_sections = sections(left), sections(right)
    all_names = sorted(set(left_sections) | set(right_sections))
    differences = [name for name in all_names if left_sections.get(name) != right_sections.get(name)]
    alloc_names = [name for name in all_names
                   if left_sections.get(name, {}).get('flags', 0) & 2 or right_sections.get(name, {}).get('flags', 0) & 2]
    alloc_differences = [name for name in alloc_names if left_sections.get(name) != right_sections.get(name)]
    for side, path in [('actual', left), (label, right)]:
        verify.run(out, side + '-readelf', ['aarch64-linux-gnu-readelf', '-h', '-SW', '-Wr', str(path)])
        verify.run(out, side + '-objdump', ['aarch64-linux-gnu-objdump', '-dr', str(path)])
        verify.run(out, side + '-strip-debug', ['aarch64-linux-gnu-objcopy', '--strip-debug',
                                               str(path), str(out / (side + '-no-debug.o'))])
    # Only normalize objdump's filename banner. Instructions, labels and normal
    # relocation markers remain intact, with no rewriting of symbols/offsets.
    disassembly = {}
    for side in ['actual', label]:
        text = (out / (side + '-objdump.stdout')).read_text()
        disassembly[side] = re.sub(r'^.+:\s+file format elf64-littleaarch64$',
                                   'OBJECT: file format elf64-littleaarch64', text, flags=re.M)
        (out / (side + '-objdump-filename-normalized.txt')).write_text(disassembly[side])
    result = {'actual_object_bytes': left.stat().st_size, 'actual_object_sha256': verify.file_sha(left),
              label + '_object_bytes': right.stat().st_size, label + '_object_sha256': verify.file_sha(right),
              'whole_object_equal': left.read_bytes() == right.read_bytes(),
              'text_section_equal': left_sections.get('.text') == right_sections.get('.text'),
              'all_alloc_section_bytes_sizes_flags_equal': not alloc_differences,
              'alloc_sections_compared': len(alloc_names), 'alloc_section_differences': alloc_differences,
              'all_section_differences': differences,
              'objdump_instructions_labels_relocation_markers_equal_after_filename_banner_only': disassembly['actual'] == disassembly[label],
              'objects_equal_after_GNU_strip_debug_only': (out / 'actual-no-debug.o').read_bytes() == (out / (label + '-no-debug.o')).read_bytes(),
              'actual_sections': left_sections, label + '_sections': right_sections}
    verify.save(out / 'comparison.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verification', type=Path, default=HERE / 'verification-v1')
    parser.add_argument('--out', type=Path, default=HERE / 'builtin-object-v2')
    args = parser.parse_args()
    previous = args.verification.resolve(strict=True)
    out = args.out.absolute()
    if previous.parent != HERE or out.parent.resolve() != HERE or out.exists() or out.is_symlink():
        raise ValueError('Use owned prior verification and fresh builtin output')
    receipt = json.loads((previous / 'receipt.json').read_text())
    if receipt['exit'] != 0 or verify.file_sha(ACTUAL_OBJECT) != ACTUAL_OBJECT_SHA:
        raise ValueError('Need actual Image-v3 object and successful public replay')
    replay = previous / 'work/sdk-replay'
    old_module_object = previous / 'kbuild/objects/rockchip_i2s_tdm.o'
    if verify.file_sha(old_module_object) != receipt['new_object']['object_sha256']:
        raise ValueError('Prior obj-m result changed')
    expected_source = json.loads((previous / 'source/tracked-source-inventory.json').read_text())
    before_abi = verify.abi_inventory(verify.ABI)
    before_actual_diff = verify.git(verify.ACTUAL, 'diff', '--binary', '--no-ext-diff', 'HEAD')
    before_actual_status = verify.git(verify.ACTUAL, 'status', '--porcelain=v1', '--untracked-files=all')
    external = {str(path.relative_to(ROOT)): verify.file_sha(path)
                for path in [ACTUAL_OBJECT, ACTUAL_COMMAND, verify.ACTUAL / verify.CPU, old_module_object,
                             verify.RUNTIME / 'build/integration-v3/Image',
                             verify.RUNTIME / 'build/integration-v3/manifest.json']}
    # Match the existing actual Image builder's task-local host tool path.
    # No installation, service/global environment change or network operation.
    host_bin = ROOT / '.deps/host-tools/bin'
    host_tools = {name: {'path': str((host_bin / name).resolve(strict=True)),
                         'sha256': verify.file_sha((host_bin / name).resolve(strict=True))}
                  for name in ['flex', 'bison', 'm4']}
    os.environ['PATH'] = str(host_bin) + ':' + os.environ['PATH']
    if verify.file_sha(verify.ABI / '.config') != '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912':
        raise ValueError('Actual reviewed configuration changed')
    out.mkdir()
    shadow = out / 'work/kernel-output'
    shadow.mkdir(parents=True)
    for relative in verify.COPY_DIRS:
        shutil.copytree(verify.ABI / relative, shadow / relative)
    for relative in verify.COPY_FILES:
        shutil.copy2(verify.ABI / relative, shadow / relative)
    if verify.abi_inventory(shadow) != before_abi:
        raise ValueError('Pre-build shadow ABI/config copy mismatch')
    argv = ['make', '-C', str(replay), 'O=' + str(shadow), 'ARCH=arm64',
            'CROSS_COMPILE=aarch64-linux-gnu-', 'V=1', '-j2',
            'sound/soc/rockchip/rockchip_i2s_tdm.o']
    verify.run(out, 'built-in-kbuild', argv, timeout=240)
    built = shadow / 'sound/soc/rockchip/rockchip_i2s_tdm.o'
    command = shadow / 'sound/soc/rockchip/.rockchip_i2s_tdm.o.cmd'
    first_command = command.read_text().splitlines()[0]
    if ' -DMODULE ' in first_command or 'KBUILD_MODFILE' not in first_command or 'snd_soc_rockchip_i2s_tdm' not in first_command:
        raise ValueError('Fresh target did not use actual built-in compilation identity')
    if verify.file_sha(shadow / '.config') != verify.file_sha(verify.ABI / '.config') or \
            verify.tracked_inventory(replay) != expected_source or verify.abi_inventory(verify.ABI) != before_abi or \
            verify.git(verify.ACTUAL, 'diff', '--binary', '--no-ext-diff', 'HEAD') != before_actual_diff or \
            verify.git(verify.ACTUAL, 'status', '--porcelain=v1', '--untracked-files=all') != before_actual_status or \
            verify.git(verify.SDK, 'status', '--porcelain=v1', '--untracked-files=all'):
        raise ValueError('Original/replayed source or actual ABI/config changed')
    snapshots = out / 'objects'
    snapshots.mkdir()
    for path, name in [(ACTUAL_OBJECT, 'actual-built-in.o'), (ACTUAL_COMMAND, 'actual-built-in.cmd'),
                       (built, 'public-built-in.o'), (command, 'public-built-in.cmd'),
                       (old_module_object, 'previous-external-obj-m.o'),
                       (shadow / '.config', 'actual-configuration-copy')]:
        shutil.copy2(path, snapshots / name)
    comparisons = {}
    for label, path in [('public-built-in', snapshots / 'public-built-in.o'),
                        ('previous-obj-m', snapshots / 'previous-external-obj-m.o')]:
        directory = out / label
        directory.mkdir()
        comparisons[label] = compare(directory, label, snapshots / 'actual-built-in.o', path)
    for name, digest in external.items():
        if verify.file_sha(ROOT / name) != digest:
            raise ValueError('Read-only comparison changed original input')
    for name, row in host_tools.items():
        if verify.file_sha(Path(row['path'])) != row['sha256']:
            raise ValueError('Existing host tool changed: ' + name)
    verify.save(out / 'actual-ABI-before.json', before_abi)
    verify.save(out / 'external-inputs.json', external)
    result = {'exit': 0, 'target': 'sound/soc/rockchip/rockchip_i2s_tdm.o',
              'actual_source_CPU_sha256': verify.CPU_SHA, 'replayed_source_files_verified': len(expected_source),
              'actual_ABI_before_and_after_files': len(before_abi),
              'actual_configuration_sha256': verify.file_sha(verify.ABI / '.config'),
              'public_builtin_object_bytes': built.stat().st_size, 'public_builtin_object_sha256': verify.file_sha(built),
              'actual_builtin_object_bytes': ACTUAL_OBJECT.stat().st_size, 'actual_builtin_object_sha256': ACTUAL_OBJECT_SHA,
              'new_builtin_command_sha256': verify.file_sha(command),
              'existing_actual_builder_host_tool_PATH_prefix': str(host_bin),
              'existing_host_tools': host_tools,
              'built_in_without_MODULE': True, 'original_inputs_unchanged': True,
              'comparisons': {name: {key: value for key, value in row.items() if not key.endswith('_sections')}
                              for name, row in comparisons.items()},
              'new_Image_built': False, 'hardware_operated': False,
              'boundary': 'Actual built-in Kbuild target, same public source and actual config, with finite read-only ELF comparisons. Previous external obj-m used different MODULE/MODNAME identity and is not the Image object.'}
    verify.save(out / 'receipt.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
