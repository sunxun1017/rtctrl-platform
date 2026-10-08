#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Private obj-y Kbuild checks; no Image, module, or board config is changed."""
from pathlib import Path
import argparse
import hashlib
import difflib
import json
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KERNEL = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v3'
ABI = ROOT / '.deps/kernel/aiot-3568pq-audio-v3'
COPY_DIRS = ['include', 'arch/arm64/include', 'scripts']
COPY_FILES = ['.config', 'Module.symvers', 'vmlinux.symvers', 'Makefile']
SOURCES = ['sound/soc/soc-pcm.c', 'sound/soc/soc-component.c',
           'sound/soc/generic/simple-card-utils.c', 'sound/soc/soc-compress.c']


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def inventory(root, paths, allow_source_links=False):
    result = {}
    for name in paths:
        path = root / name
        if path.is_symlink() or not path.exists():
            raise ValueError('Missing or symlink input: ' + str(path))
        for p in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if p.is_symlink() and not allow_source_links:
                raise ValueError('Symlink input: ' + str(p))
            if p.is_symlink() and not p.resolve().is_relative_to(root.resolve()):
                raise ValueError('Source link escapes input tree: ' + str(p))
            if p.is_file():
                result[p.relative_to(root).as_posix()] = (sha(p) if not p.is_symlink() else
                    {'resolved_sha256': sha(p), 'link_target': str(p.readlink()),
                     'resolved_relative': p.resolve().relative_to(root.resolve()).as_posix()})
    return result


def inputs():
    manifest = json.loads((HERE / 'source-manifest-v1.json').read_text())
    protected = {}
    for name, item in manifest['inputs'].items():
        if sha(ROOT / name) != item['sha256'] or sha(HERE / item['snapshot']) != item['sha256']:
            raise ValueError('Original/snapshot changed: ' + name)
        protected[name] = item['sha256']
    for name, item in manifest['files'].items():
        if sha(HERE / 'source-v1' / name) != item['sha256']:
            raise ValueError('Candidate changed: ' + name)
        protected['outputs/rk3568-audio-runtime-20261005/asoc-open-rollback-v1/source-v1/' + name] = item['sha256']
    if sha(HERE / 'candidate-v1.patch') != manifest['patch_sha256']:
        raise ValueError('Patch changed')
    return protected


def run(out, label, argv, timeout=120):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    (out / (label + '.stdout')).write_text(p.stdout)
    (out / (label + '.stderr')).write_text(p.stderr)
    return {'label': label, 'argv': argv, 'exit': p.returncode,
            'stdout_sha256': sha(out / (label + '.stdout')),
            'stderr_sha256': sha(out / (label + '.stderr'))}


def copy_abi(out):
    shadow = out / 'kernel-abi'
    shadow.mkdir()
    for name in COPY_DIRS:
        shutil.copytree(ABI / name, shadow / name)
    for name in COPY_FILES:
        shutil.copy2(ABI / name, shadow / name)
    return shadow


def branch_config(shadow, out):
    """Select just the otherwise-disabled source branch in a private check ABI."""
    delta = ['CONFIG_SND_SOC_COMPRESS', 'CONFIG_SND_COMPRESS_OFFLOAD']
    files = {'.config': lambda n: n + '=y',
             'include/config/auto.conf': lambda n: n + '=y',
             'include/generated/autoconf.h': lambda n: '#define ' + n + ' 1'}
    record = {}
    for name, line in files.items():
        p = shadow / name
        text = p.read_text()
        if any(n in text for n in delta):
            raise ValueError('Unexpected original compressed flag: ' + name)
        original = sha(p)
        original_text = text
        p.write_text(text + '\n' + '\n'.join(line(n) for n in delta) + '\n')
        diff_path = out / (name.replace('/', '_') + '.diff')
        diff_path.write_text(''.join(difflib.unified_diff(original_text.splitlines(True),
                            p.read_text().splitlines(True), fromfile='original/' + name,
                            tofile='private-branch/' + name)))
        record[name] = {'original_sha256': original, 'sha256': sha(p),
                        'exact_appended_lines': [line(n) for n in delta],
                        'diff_sha256': sha(diff_path)}
    return record


def build(out, source_names, shadow, compiler, config_delta):
    objects = out / 'objects'
    objects.mkdir()
    for name in source_names:
        shutil.copy2(HERE / 'source-v1' / name, objects / Path(name).name)
    basenames = [Path(n).stem for n in source_names]
    (objects / 'Makefile').write_text('# Private object-only built-in validation.\nobj-y := ' +
                                    ' '.join(n + '.o' for n in basenames) + '\n')
    paths = [KERNEL / 'arch/arm64/include', shadow / 'arch/arm64/include/generated',
             KERNEL / 'include', shadow / 'include', KERNEL / 'arch/arm64/include/uapi',
             shadow / 'arch/arm64/include/generated/uapi', KERNEL / 'include/uapi',
             shadow / 'include/generated/uapi']
    includes = ' '.join('-I' + str(p) for p in paths) + ' -include ' + str(KERNEL / 'include/linux/kconfig.h')
    argv = ['make', '-C', str(shadow), 'M=' + str(objects), 'ARCH=arm64',
            'CROSS_COMPILE=aarch64-linux-gnu-', 'LINUXINCLUDE=' + includes,
            'V=1', '-j2', 'built-in.a']
    result = {'steps': [run(out, 'build', argv)], 'compiler': compiler,
              'config_sha256': sha(shadow / '.config'), 'config_delta': config_delta,
              'source_branch_check_only': bool(config_delta), 'objects': {},
              'branch_Kconfig_generated': False if config_delta else None,
              'branch_ABI_or_board_config_accepted': False,
              'kbuild_Makefile_sha256': sha(objects / 'Makefile')}
    if result['steps'][0]['exit']:
        return result
    for name in source_names:
        base = Path(name).stem
        obj = objects / (base + '.o')
        cmd = objects / ('.' + base + '.o.cmd')
        data = obj.read_bytes()
        if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', data, 16) != (1, 183):
            raise ValueError('Need AArch64 relocatable object')
        command = cmd.read_text().splitlines()[0]
        if '-DMODULE' in command or str(objects / Path(name).name) not in command:
            raise ValueError('Wrong module/source compilation: ' + name)
        result['objects'][name] = {'source_sha256': sha(objects / Path(name).name),
                                  'object_sha256': sha(obj), 'bytes': len(data),
                                  'command_sha256': sha(cmd), 'module_flag_absent': True,
                                  'actual_compile_command': command}
        result['steps'].append(run(out, base + '-nm', ['aarch64-linux-gnu-nm', '-a', str(obj)]))
    archive = objects / 'built-in.a'
    result['steps'].append(run(out, 'archive-members', ['aarch64-linux-gnu-ar', 't', str(archive)]))
    members = (out / 'archive-members.stdout').read_text().splitlines()
    if [Path(n).name for n in members] != [n + '.o' for n in basenames]:
        raise ValueError('Unexpected archive membership')
    result.update({'built_in_archive_sha256': sha(archive), 'archive_members': members,
                   'no_module_generated': not list(objects.glob('*.ko'))})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    attempt = parser.parse_args().attempt
    if not attempt.startswith('v') or not attempt[1:].isdigit():
        raise ValueError('Numeric version required')
    out = HERE / ('kbuild-' + attempt)
    out.mkdir(exist_ok=False)
    shutil.copy2(Path(__file__), out / 'build-builtin.py')
    before_inputs = inputs()
    before_abi = inventory(ABI, COPY_DIRS + COPY_FILES)
    before_kernel = inventory(KERNEL, ['include', 'arch/arm64/include', 'scripts', 'Makefile',
                                     'sound/soc/Makefile', 'sound/soc/Kconfig', 'sound/core/Kconfig'], True)
    if before_abi['.config'] != '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912':
        raise ValueError('Wrong ABI config')
    compiler = subprocess.check_output(['aarch64-linux-gnu-gcc', '--version'], text=True).splitlines()[0]
    if compiler != 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0':
        raise ValueError('Wrong compiler')
    normal = out / 'current-config'
    normal.mkdir()
    shadow = copy_abi(normal)
    if inventory(shadow, COPY_DIRS + COPY_FILES) != before_abi:
        raise ValueError('ABI copy differs')
    normal_result = build(normal, SOURCES[:3], shadow, compiler, {})
    (normal / 'result.json').write_text(json.dumps(normal_result, indent=2) + '\n')
    branch = out / 'compressed-branch'
    branch.mkdir()
    shadow_branch = copy_abi(branch)
    if inventory(shadow_branch, COPY_DIRS + COPY_FILES) != before_abi:
        raise ValueError('ABI branch copy differs')
    delta = branch_config(shadow_branch, branch)
    branch_result = build(branch, SOURCES[3:], shadow_branch, compiler, delta)
    (branch / 'result.json').write_text(json.dumps(branch_result, indent=2) + '\n')
    unchanged = (inputs() == before_inputs and inventory(ABI, COPY_DIRS + COPY_FILES) == before_abi and
                 inventory(KERNEL, ['include', 'arch/arm64/include', 'scripts', 'Makefile',
                                    'sound/soc/Makefile', 'sound/soc/Kconfig', 'sound/core/Kconfig'], True) == before_kernel)
    receipt = {'schema': 'rk3568-asoc-private-builtin-v1', 'protected_sha256': before_inputs,
               'abi_inputs_sha256': before_abi, 'kernel_inputs_sha256': before_kernel,
               'current_config_result': normal_result, 'compressed_branch_result': branch_result,
               'original_inputs_and_ABI_unchanged': unchanged, 'full_image_built': False,
               'board_config_compressed_enabled': False, 'board_tested': False,
               'compressed_only_preprocessor_branch_check': True,
               'compressed_branch_Kconfig_generated': False,
               'compressed_branch_ABI_validated': False,
               'compressed_flags_Kconfig_evidence': {'source': 'sound/soc/Kconfig',
                    'sha256': before_kernel['sound/soc/Kconfig'],
                    'core_Kconfig_sha256': before_kernel['sound/core/Kconfig'],
                    'SND_SOC_COMPRESS': 'bool inside if SND_SOC; selects SND_COMPRESS_OFFLOAD',
                    'SND_COMPRESS_OFFLOAD': 'tristate inside sound/core/Kconfig if SND'},
               'module_built_or_loaded': False, 'builder_sha256': sha(out / 'build-builtin.py')}
    valid = unchanged and all(step['exit'] == 0 for item in [normal_result, branch_result] for step in item['steps'])
    receipt['accepted_offline_object_check'] = valid
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'accepted': valid, 'unchanged': unchanged,
                      'objects': list(normal_result['objects']) + list(branch_result['objects']),
                      'board_tested': False}))
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
