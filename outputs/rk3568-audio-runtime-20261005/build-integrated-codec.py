#!/usr/bin/env python3
"""Build the frozen codec against the completed audio Image's actual ABI."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v1'
BUILD = ROOT / '.deps/kernel/aiot-3568pq-audio-v1'
IMAGE = HERE / 'build/integration-v1'
OUT = HERE / 'build/integrated-codec-v1'
CODEC_SHA = '72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64'
HEADER_SHA = '370f2c9451d0e871b627c7b9a9b90cc24e486c49cebe29c068d5b692f7802449'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory():
    paths = [BUILD / '.config', BUILD / 'Module.symvers', BUILD / 'vmlinux.symvers']
    for relative in ['include', 'arch/arm64/include']:
        paths += [path for path in (BUILD / relative).rglob('*') if path.is_file()]
    return {str(path.relative_to(BUILD)): sha(path) for path in sorted(paths)}


def main():
    record = json.loads((IMAGE / 'manifest.json').read_text())
    for path, expected in [(IMAGE / 'Image', record['image_sha256']),
                           (BUILD / 'arch/arm64/boot/Image', record['image_sha256']),
                           (BUILD / '.config', record['config_sha256']),
                           (BUILD / 'Module.symvers', record['module_symvers_sha256']),
                           (BUILD / 'vmlinux.symvers', record['vmlinux_symvers_sha256']),
                           (SOURCE / 'sound/soc/codecs/rk817_codec.c', CODEC_SHA),
                           (SOURCE / 'sound/soc/codecs/rk817_codec.h', HEADER_SHA)]:
        if path.is_symlink() or sha(path) != expected:
            raise ValueError('Integrated source/ABI changed: ' + str(path))
    if record['build_exit_code'] or OUT.exists() or OUT.is_symlink():
        raise ValueError('Completed build and fresh codec directory required')
    before = inventory()
    OUT.mkdir(parents=True)
    modules = OUT / 'modules'
    modules.mkdir()
    for name in ['rk817_codec.c', 'rk817_codec.h']:
        shutil.copyfile(SOURCE / 'sound/soc/codecs' / name, modules / name)
    (modules / 'Makefile').write_text('obj-m += snd-soc-rk817.o\nsnd-soc-rk817-objs := rk817_codec.o\n')
    argv = ['make', '-C', str(SOURCE), 'O=' + str(BUILD), 'M=' + str(modules),
            'ARCH=arm64', 'CROSS_COMPILE=aarch64-linux-gnu-', 'V=1', '-j2', 'modules']
    env = dict(os.environ)
    env['PATH'] = str(ROOT / '.deps/host-tools/bin') + ':' + env['PATH']
    with (OUT / 'build.txt').open('w') as stream:
        result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        raise ValueError('New-Image codec build failed; evidence preserved')
    after = inventory()
    if before != after:
        raise ValueError('New Image ABI modified during codec build')
    loader = importlib.util.spec_from_file_location('codec_audit', ROOT / 'outputs/rk3568-audio-20261005/build-codec.py')
    audit = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(audit)
    expected_release = '5.10.160-rt89-g9f9e9d18574d-dirty'
    if record['kernel_release'] != expected_release or audit.RELEASE != expected_release:
        raise ValueError('Unexpected Image/module release')
    exports = audit.symbols(BUILD / 'Module.symvers')
    module = modules / 'snd-soc-rk817.ko'
    information = audit.audit_module(module, OUT, exports)
    own_exports = audit.symbols(modules / 'Module.symvers')
    if own_exports or any(value['provider'] != 'vmlinux' for value in information['imports'].values()):
        raise ValueError('Codec must import only this Image built-ins and export nothing')
    manifest = {'image_sha256': record['image_sha256'], 'image_manifest_sha256': sha(IMAGE / 'manifest.json'),
                'module': information, 'source_sha256': CODEC_SHA, 'header_sha256': HEADER_SHA,
                'abi_inventory': before, 'abi_unchanged': True,
                'module_symvers_sha256': record['module_symvers_sha256'], 'build_argv': argv,
                'builder_sha256': sha(Path(__file__)), 'audit_source_sha256': sha(Path(audit.__file__)),
                'board_tested': False, 'unload_tested': False, 'deployed': False}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'bytes': information['bytes'], 'sha256': information['sha256'],
                      'imports': len(information['imports']), 'abi_files': len(before)}))


if __name__ == '__main__':
    main()
