#!/usr/bin/env python3
"""Prepare the actual sealed v3 files for a separate RAM-only board trial."""
import argparse
import hashlib
import json
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / 'outputs/rk3568-audio-package-20261005/build'
OUT = HERE / 'build/board-audio-v3'
REMOTE = '/cache/rtctrl-audio-bootm-20261005-v3'
NATIVE_PID_SHA = '249cc1cfd87cbddc8618e81e6b8fd742526de78fd964d4a4b3b59b8a7d76368b'
CPU_SHA = '87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c'
GUARD_SHA = '8740384398313be87a13245e854d6fc5a17a10f3794bdd83966e933c894c6f69'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordinary(relative):
    path = ROOT / relative
    assert path.resolve().is_relative_to(ROOT) and path.is_file()
    for component in [path, *path.parents]:
        if component == ROOT:
            break
        assert not component.is_symlink(), relative
    return path


def write(name, value):
    data = value if isinstance(value, bytes) else (json.dumps(value, indent=2) + '\n').encode()
    with (OUT / name).open('xb') as stream:
        stream.write(data)


def step(command, expect=None, wait=1):
    assert all(32 <= ord(c) <= 126 for c in command) and 0 <= wait <= 60
    item = {'command': command, 'wait': wait}
    if expect:
        item['expect'] = expect
    return item


def full_sha_test(path, expected):
    return 'test "$(sha256sum ' + path + ')" = \'' + expected + '  ' + path + "'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sealed-receipt-sha256', required=True)
    args = parser.parse_args()
    receipt_path = PACKAGE / 'sealed-production-v3/receipt.json'
    assert sha(receipt_path) == args.sealed_receipt_sha256
    receipt = json.loads(receipt_path.read_text())
    assert receipt['status'] == 'RAM_ONLY_NOT_FLASH_READY'
    assert receipt['board_tested'] is False and receipt['audio_start_allowed'] is False
    assert receipt['formal_flash_ready'] is False and receipt['deployed'] is False
    package = PACKAGE / 'ram-audio-v3/boot-padded.img'
    package_bytes = package.read_bytes()
    assert len(package_bytes) == 41943040 and sha(package) == receipt['package']['sha256']
    image = json.loads((HERE / 'build/integration-v2/manifest.json').read_text())
    assert image['build_exit_code'] == 0 and image['cpu_source_sha256'] == CPU_SHA
    assert image['battery_algorithm_enabled'] is False
    assert image['review_gate_sha256'] == '56ec8e396811c6b970ebb693db1fbd14b484fd4e54c321a011431201062e7af6'
    assert sha(HERE / 'build/integration-v2/Image') == image['image_sha256']
    assert sha(HERE / 'build/audio-ram-shim-v1/applied-audit-only.dtb') == \
        '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'
    old = HERE / 'build/board-audio-v2/input-manifest.json'
    assert sha(old) == '0819c18904fd791ed9c08f84f324b5660d1831befc2f98fe4caaeb1c4fa1e46b'
    protected = json.loads(old.read_text())
    runtime = receipt['runtime']['files']
    assert set(runtime) == {'snd-soc-rk817.ko', 'alsa-inspect', 'pcm-transfer', 'audio-session-guard'}
    assert runtime['audio-session-guard']['sha256'] == GUARD_SHA
    codec = json.loads((HERE / 'build/integrated-codec-v2/manifest.json').read_text())
    assert codec['image_sha256'] == image['image_sha256']
    assert codec['image_manifest_sha256'] == sha(HERE / 'build/integration-v2/manifest.json')
    assert codec['module']['sha256'] == runtime['snd-soc-rk817.ko']['sha256']
    files = {'boot-audio.img': package}
    for name, entry in runtime.items():
        path = ordinary(entry['path'])
        assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], name
        files[name] = path
    assert not OUT.exists() and not OUT.is_symlink()
    OUT.mkdir(parents=True)

    script = '''#!/bin/sh
set -eu
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/pid1
'''
    script += full_sha_test('/proc/1/exe', NATIVE_PID_SHA) + '\n'
    script += '''test -z "$(cat /proc/modules)"
test ! -e /tmp/audio
test ! -L /tmp/audio
test ! -e /dev/McuCom
'''
    backing = '/.backing-cache' + REMOTE[len('/cache'):]
    for name, entry in runtime.items():
        script += full_sha_test(backing + '/' + name, entry['sha256']) + '\n'
    script += 'mkdir -m 700 /tmp/audio\n'
    for name in runtime:
        destination = 'audio-session-guard-v4' if name == 'audio-session-guard' else name
        script += 'cp ' + backing + '/' + name + ' /tmp/audio/' + destination + '\n'
        script += full_sha_test('/tmp/audio/' + destination, runtime[name]['sha256']) + '\n'
    script += 'chmod 500 /tmp/audio/alsa-inspect /tmp/audio/pcm-transfer /tmp/audio/audio-session-guard-v4\n'
    script += 'echo AUDIO_PACKAGE_V3_RAM_AUX_VERIFIED_NO_MODULE_OR_START\n'
    data = script.encode('ascii')
    assert b'\r' not in data
    write('stage-aux.sh', data)
    files['stage-aux.sh'] = OUT / 'stage-aux.sh'
    write('audio-files.sha256', ''.join(sha(path) + '  ' + name + '\n'
                                       for name, path in files.items() if name != 'boot-audio.img').encode())
    files['audio-files.sha256'] = OUT / 'audio-files.sha256'
    manifest = {
        'host_verified': True, 'mode': 'RAM_ONLY_NOT_FLASH_READY',
        'files': [{'name': name, 'source': path.relative_to(ROOT).as_posix(),
                   'bytes': path.stat().st_size, 'sha256': sha(path)} for name, path in files.items()],
        'remote': REMOTE, 'backing_cache': backing,
        'protected_sha256': protected['protected_sha256'],
        'native_cached_sha256': protected['native_cached_sha256'],
        'sealed_package_receipt_sha256': args.sealed_receipt_sha256,
        'image_sha256': image['image_sha256'], 'image_manifest_sha256': sha(HERE / 'build/integration-v2/manifest.json'),
        'cpu_source_sha256': CPU_SHA, 'guard_binary_sha256': GUARD_SHA,
        'builder_sha256': sha(Path(__file__)), 'board_tested': False, 'start_allowed': False,
        'battery_algorithm_enabled': False
    }
    write('input-manifest.json', manifest)
    crc = f'{zlib.crc32(package_bytes):08x}'
    write('load.json', [step('bdinfo', wait=2),
                       step('printenv kernel_addr_r fdt_addr_r ramdisk_addr_r initrd_high fdt_high bootargs', wait=2),
                       step('ext4load mmc 0:c 20000000 ' + REMOTE[len('/cache'):] + '/boot-audio.img', '41943040 bytes read', 5),
                       step('printenv filesize', r'filesize=0x2800000'),
                       step('crc32 20000000 2800000', r'227fffff ==> ' + crc, 3)])
    write('boot.json', [step('setenv initrd_high ffffffffffffffff'), step('setenv fdt_high ffffffffffffffff'),
                       step('setenv kernel_addr_r 400000'), step('setenv ramdisk_addr_r 4000000'),
                       step('setenv fdt_addr_r a100000'),
                       step('printenv kernel_addr_r fdt_addr_r ramdisk_addr_r initrd_high fdt_high'),
                       step('bootm 20000000', r'(?m)^LINUX_PID1_ROOT_READY\r?$', 45)])
    target = '/tmp/audio-stage-package-v3.sh'
    steps = [step('test ! -e ' + target + ' && test ! -L ' + target + ' && echo AUDIO_STAGE_PACKAGE_V3_ABSENT',
                  r'(?m)^AUDIO_STAGE_PACKAGE_V3_ABSENT\r?$')]
    for offset in range(0, len(data), 96):
        encoded = ''.join('\\0' + f'{byte:03o}' for byte in data[offset:offset + 96])
        steps.append(step("printf '%b' '" + encoded + "' " + ('>' if offset == 0 else '>>') + ' ' + target, wait=0.05))
    steps.append(step(full_sha_test(target, sha(OUT / 'stage-aux.sh')) + ' && sh ' + target,
                      r'(?m)^AUDIO_PACKAGE_V3_RAM_AUX_VERIFIED_NO_MODULE_OR_START\r?$', 5))
    write('copy-aux.json', steps)
    print(json.dumps({'files': len(files), 'bytes': sum(x['bytes'] for x in manifest['files']),
                      'package_crc32': crc, 'manifest_sha256': sha(OUT / 'input-manifest.json'),
                      'board_tested': False, 'start_allowed': False}))


if __name__ == '__main__':
    main()
