#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Freeze finite replay/object evidence; leave SDK/ABI scratch caches external."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches'


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected ordinary file: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verification', type=Path, default=HERE / 'verification-v1')
    parser.add_argument('--builtin', type=Path, default=HERE / 'builtin-object-v2')
    parser.add_argument('--out', type=Path, default=HERE / 'sealed-evidence-v1')
    args = parser.parse_args()
    verification = args.verification.resolve(strict=True)
    builtin = args.builtin.resolve(strict=True)
    out = args.out.absolute()
    if verification.parent != HERE or builtin.parent != HERE or out.parent.resolve() != HERE or out.exists() or out.is_symlink():
        raise ValueError('Use existing verification and fresh seal inside owned directory')
    receipt = json.loads((verification / 'receipt.json').read_text())
    if receipt['exit'] != 0 or receipt['complete_tracked_source_bytes_and_modes_equal_actual_v3'] is not True \
            or receipt['new_object']['exit'] != 0 or receipt['protected_inputs_unchanged'] is not True:
        raise ValueError('Need successful executed source/object verification')
    builtin_receipt = json.loads((builtin / 'receipt.json').read_text())
    if builtin_receipt['exit'] != 0 or builtin_receipt['built_in_without_MODULE'] is not True or \
            builtin_receipt['original_inputs_unchanged'] is not True or \
            builtin_receipt['actual_source_CPU_sha256'] != receipt['CPU_full_source_sha256']:
        raise ValueError('Need successful actual built-in target verification')
    external = json.loads((verification / 'external-inputs.json').read_text())
    for name, digest in json.loads((builtin / 'external-inputs.json').read_text()).items():
        if name in external and external[name] != digest:
            raise ValueError('External inputs differ between executions')
        external[name] = digest
    for row in builtin_receipt['existing_host_tools'].values():
        name = Path(row['path']).relative_to(ROOT).as_posix()
        external[name] = row['sha256']
    for name, digest in external.items():
        if sha(ROOT / name) != digest:
            raise ValueError('External input changed: ' + name)
    # All public files, including the prior twelve, must match their executed copies.
    patches = receipt['public_patch_sequence']
    for row in patches:
        path = ROOT / row['public_patch']
        if sha(path) != row['patch_sha256'] or path.read_bytes() != (verification / 'patches' / path.name).read_bytes():
            raise ValueError('Current/executed public patch changed')
    output_files = {}
    roots = {'public-replay': verification, 'builtin': builtin,
             'initial-builtin-PATH-failure': HERE / 'builtin-object-v1'}
    for label, directory in roots.items():
        for path in sorted(directory.rglob('*')):
            relative = path.relative_to(directory)
            if relative.parts[0] == 'work':
                continue
            if path.is_symlink():
                raise ValueError('Evidence symlink')
            if path.is_file():
                output_files[label + '/' + relative.as_posix()] = sha(path)
    if sha(verification / 'source/rockchip_i2s_tdm.c') != receipt['CPU_full_source_sha256'] or \
            sha(verification / 'kbuild/objects/rockchip_i2s_tdm.o') != receipt['new_object']['object_sha256']:
        raise ValueError('Executed source/object changed')
    tools = ['prepare-patches.py', 'verify-public-series.py', 'verify-builtin-object.py',
             'freeze-evidence.py', 'README.md']
    tool_files = {name: sha(HERE / name) for name in tools}
    out.mkdir()
    for name in tools:
        target = out / 'tools' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / name, target)
    for name in output_files:
        target = out / 'executed' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        label, relative = name.split('/', 1)
        shutil.copy2(roots[label] / relative, target)
    summary = {'exit': 0, 'CPU_source_sha256': receipt['CPU_full_source_sha256'],
               'new_public_patches_sha256': {Path(row['public_patch']).name: row['patch_sha256']
                                             for row in patches[12:]},
               'verification_receipt_sha256': sha(verification / 'receipt.json'),
               'tracked_source_files_verified': receipt['tracked_source_files_verified'],
               'actual_v3_ABI_files_verified': receipt['actual_v3_ABI_files_verified'],
               'new_object_sha256': receipt['new_object']['object_sha256'],
               'builtin_receipt_sha256': sha(builtin / 'receipt.json'),
               'new_builtin_object_sha256': builtin_receipt['public_builtin_object_sha256'],
               'actual_builtin_object_sha256': builtin_receipt['actual_builtin_object_sha256'],
               'builtin_object_comparisons': builtin_receipt['comparisons'],
               'copied_execution_files': len(output_files), 'copied_tools': len(tool_files),
               'external_inputs_reverified': len(external),
               'old_public_patches_unchanged': True, 'new_Image_built': False,
               'hardware_operated': False, 'formal_flash_validated': False,
               'freeze_scope': 'Copied finite tools, all14 patches, full CPU source, complete tracked-source inventory/diff, actual ABI inventory, external and actual-target built-in Kbuild objects/ELF comparisons/receipts, and the first built-in preparation PATH failure. SDK clone, shadow ABI and Git metadata under work are disposable caches and are not archived. Existing Image/root models/raw board logs remain SHA-bound external inputs.'}
    save(out / 'external-inputs-union.json', external)
    save(out / 'receipt.json', summary)
    internal = {path.relative_to(out).as_posix(): sha(path) for path in sorted(out.rglob('*')) if path.is_file()}
    save(out / 'frozen-output-manifest.json', {'files_sha256': internal, 'freeze_scope': summary['freeze_scope']})
    internal['frozen-output-manifest.json'] = sha(out / 'frozen-output-manifest.json')
    with (out / 'SHA256SUMS').open('x', encoding='utf-8') as handle:
        handle.write(''.join(digest + '  ' + name + '\n' for name, digest in sorted(internal.items())))
    for name, digest in internal.items():
        if sha(out / name) != digest:
            raise ValueError('Final freeze readback mismatch')
    if {name: sha(HERE / name) for name in tools} != tool_files or \
            {name: sha(roots[name.split('/', 1)[0]] / name.split('/', 1)[1]) for name in output_files} != output_files:
        raise ValueError('Freeze source changed while copying')
    print(json.dumps({'exit': 0, 'receipt_sha256': sha(out / 'receipt.json'),
                      'inventory_sha256': sha(out / 'frozen-output-manifest.json'),
                      'SHA256SUMS_sha256': sha(out / 'SHA256SUMS'),
                      'inventory_files': len(internal) - 1, 'sum_files': len(internal)}, indent=2))


if __name__ == '__main__':
    main()
