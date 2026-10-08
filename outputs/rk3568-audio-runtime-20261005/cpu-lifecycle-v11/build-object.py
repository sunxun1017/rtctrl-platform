#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Full production CPU object against shadow copies of actual integrated ABI."""
from pathlib import Path
import hashlib
import json
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KERNEL = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v1'
ABI = ROOT / '.deps/kernel/aiot-3568pq-audio-v1'
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
COPY_DIRS = ['include', 'arch/arm64/include', 'scripts']
COPY_FILES = ['.config', 'Module.symvers', 'vmlinux.symvers', 'Makefile']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory):
    result = {}
    for relative in COPY_DIRS + COPY_FILES:
        path = directory / relative
        if path.is_symlink() or not path.exists():
            raise ValueError('Missing/symlink ABI input')
        for member in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if member.is_symlink():
                raise ValueError('Symlink ABI member')
            if member.is_file():
                result[member.relative_to(directory).as_posix()] = sha(member)
    return result


def protected():
    manifest = json.loads((HERE / 'input-manifest.json').read_text())
    for name, digest in manifest['protected_sha256'].items():
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or sha(path) != digest:
            raise ValueError('Protected input changed: ' + name)
    return manifest['protected_sha256']


def run(output, label, argv, timeout=120):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    (output / (label + '.stdout')).write_text(result.stdout)
    (output / (label + '.stderr')).write_text(result.stderr)
    return result


def main():
    out = HERE / 'kbuild-object-v1'
    out.mkdir(exist_ok=False)
    protected_sha = protected()
    candidate = json.loads((HERE / 'source/manifest.json').read_text())
    source_path = HERE / 'source' / SOURCE
    if sha(source_path) != candidate['source_sha256']:
        raise ValueError('Candidate source mismatch')
    if sha(ABI / '.config') != '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912' or \
            sha(ABI / 'Module.symvers') != '64eed1c187aa0611b1281a74bdcb62d5e79e21929afb4b684e9bb2941b275aea':
        raise ValueError('Need actual integrated Image ABI')
    config = (ABI / '.config').read_text().splitlines()
    required = ['CONFIG_SND_SOC_ROCKCHIP_I2S_TDM=y', 'CONFIG_SND_SOC_GENERIC_DMAENGINE_PCM=y',
                'CONFIG_SND_DMAENGINE_PCM=y', 'CONFIG_PL330_DMA=y', 'CONFIG_PM=y',
                'CONFIG_PM_SLEEP=y', 'CONFIG_NO_GKI=y',
                '# CONFIG_SND_SOC_ROCKCHIP_I2S_TDM_MULTI_LANES is not set']
    if any(line not in config for line in required):
        raise ValueError('Integrated config profile mismatch')
    before = inventory(ABI)
    compiler = subprocess.check_output(['aarch64-linux-gnu-gcc', '--version'], text=True).splitlines()[0]
    if compiler != 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0':
        raise ValueError('Compiler differs from actual Image')
    shadow = out / 'kernel-abi'
    shadow.mkdir()
    for relative in COPY_DIRS:
        shutil.copytree(ABI / relative, shadow / relative)
    for relative in COPY_FILES:
        shutil.copy2(ABI / relative, shadow / relative)
    if inventory(shadow) != before:
        raise ValueError('Shadow ABI changed during copying')
    objects = out / 'objects'
    objects.mkdir()
    shutil.copy2(source_path, objects / 'rockchip_i2s_tdm.c')
    headers = {}
    for filename in ['rockchip_i2s_tdm.h', 'rockchip_dlp.h']:
        path = KERNEL / 'sound/soc/rockchip' / filename
        shutil.copy2(path, objects / filename)
        headers[filename] = sha(path)
    (objects / 'Makefile').write_text('# Object-only validation; no Image or module.\nobj-m += rockchip_i2s_tdm.o\n')
    paths = [KERNEL / 'arch/arm64/include', shadow / 'arch/arm64/include/generated',
             KERNEL / 'include', shadow / 'include', KERNEL / 'arch/arm64/include/uapi',
             shadow / 'arch/arm64/include/generated/uapi', KERNEL / 'include/uapi',
             shadow / 'include/generated/uapi']
    includes = ' '.join('-I' + str(path) for path in paths) + ' -include ' + str(KERNEL / 'include/linux/kconfig.h')
    argv = ['make', '-C', str(shadow), 'M=' + str(objects), 'ARCH=arm64',
            'CROSS_COMPILE=aarch64-linux-gnu-', 'LINUXINCLUDE=' + includes,
            'V=1', '-j2', 'rockchip_i2s_tdm.o']
    built = run(out, 'build', argv)
    (out / 'build-argv.json').write_text(json.dumps(argv, indent=2) + '\n')
    if protected() != protected_sha or inventory(ABI) != before:
        raise ValueError('Original protected source/ABI changed')
    receipt = {'exit': built.returncode, 'source_sha256': candidate['source_sha256'],
               'actual_integration_config_sha256': sha(ABI / '.config'),
               'actual_integration_Module_symvers_sha256': sha(ABI / 'Module.symvers'),
               'headers_sha256': headers, 'abi_inputs_sha256': before,
               'compiler': compiler, 'argv': argv,
               'required_actual_config': required, 'protected_sha256': protected_sha,
               'original_source_and_ABI_unchanged': True,
               'object_only': True, 'full_image_built': False, 'board_tested': False,
               'kernel_runtime_or_hardware_tested': False}
    if built.returncode:
        (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        raise RuntimeError(built.stderr + built.stdout)
    obj = objects / 'rockchip_i2s_tdm.o'
    data = obj.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', data, 16) != (1, 183):
        raise ValueError('Need ELF64 LE AArch64 ET_REL production object')
    elf = run(out, 'object-readelf', ['aarch64-linux-gnu-readelf', '-h', '-S', str(obj)])
    if elf.returncode:
        raise RuntimeError(elf.stderr)
    receipt.update({'object_bytes': len(data), 'object_sha256': sha(obj),
                    'kbuild_command_sha256': sha(objects / '.rockchip_i2s_tdm.o.cmd')})
    (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({name: receipt[name] for name in ['exit', 'source_sha256', 'object_bytes', 'object_sha256',
                                                     'original_source_and_ABI_unchanged', 'object_only', 'board_tested']}))


if __name__ == '__main__':
    main()
