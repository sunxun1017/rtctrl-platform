#!/usr/bin/env python3
"""Prepare reviewed ordinary-file staging and one RAM boot, without device I/O."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--guard-manifest-sha256', required=True)
    parser.add_argument('--guard-binary-sha256', required=True)
    args = parser.parse_args()
    guard = HERE / 'session-guard-v2/build'
    assert sha(guard / 'manifest.json') == args.guard_manifest_sha256
    assert sha(guard / 'audio-session-guard') == args.guard_binary_sha256
    package = ROOT / 'outputs/rk3568-audio-package-20261005/build/ram-audio-v2/boot-padded.img'
    assert sha(package) == '58e2a96f9da2c2ad1d60e0b42c92efa2d4c30efbfe76202738393f2e06974b8b'
    core_old = ROOT / 'outputs/rk3568-audio-package-20261005/audio-package.py'
    core_new = ROOT / 'outputs/rk3568-audio-package-20261005/audio-package-v2.py'
    expected = core_old.read_text().replace('0 < before.st_size <= limit', '0 <= before.st_size <= limit').replace(
        "manifest.get('kernel_release') == '4.19.232'", "manifest.get('kernel_release') == '5.10.160-rt89-g9f9e9d18574d-dirty'")
    for name in ['audio-package.py', 'build-audio-package.py', 'audit-audio-package.py', 'test-audio-package.py', 'README.md', 'PLAN.md']:
        stem, extension = name.rsplit('.', 1)
        expected = expected.replace("'" + name + "'", "'" + stem + '-v2.' + extension + "'")
    assert core_new.read_text() == expected, 'Only the two policy corrections and new source snapshot filenames allowed'
    audit = ROOT / 'outputs/rk3568-audio-package-20261005/build/audit-root-v1/audit.json'
    checked = json.loads(audit.read_text())
    assert checked['package']['sha256'] == sha(package)
    out = HERE / 'build/board-audio-v1'
    out.mkdir(exist_ok=False)
    files = {
        'boot-audio.img': package,
        'snd-soc-rk817.ko': HERE / 'build/integrated-codec-v1/modules/snd-soc-rk817.ko',
        'alsa-inspect': ROOT / 'outputs/rk3568-audio-20261005/build/inspect-v4/alsa-inspect',
        'pcm-transfer': ROOT / 'outputs/rk3568-audio-transfer-20261005/build/static-v1/pcm-transfer',
        'audio-session-guard': guard / 'audio-session-guard',
    }
    locks = {'snd-soc-rk817.ko': 'e0aecc775367f93555c5776938102d419865a19128b25f64d74a8e9df387ca80',
             'alsa-inspect': '118cf99482cdd65acdfae8c5e85530a76bf60c90b0b0498e8f285223f862a945',
             'pcm-transfer': '2a6c765bd9c3c25b3456e60d68670231e81dcaf7781b827559cd701beed09e2e'}
    for name, expected_sha in locks.items():
        assert sha(files[name]) == expected_sha, name
    remote = '/cache/rtctrl-audio-bootm-20261005-v1'
    stage = '''#!/bin/sh
set -eu
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/pid1
test "$(sha256sum /proc/1/exe)" = '249cc1cfd87cbddc8618e81e6b8fd742526de78fd964d4a4b3b59b8a7d76368b  /proc/1/exe'
test -z "$(cat /proc/modules)"
test ! -e /tmp/audio
test ! -L /tmp/audio
test ! -e /dev/McuCom
mkdir -m 700 /tmp/audio
cd REMOTE
sha256sum -c aux.sha256
cp snd-soc-rk817.ko alsa-inspect pcm-transfer audio-session-guard stage-aux.sh aux.sha256 /tmp/audio/
cd /tmp/audio
sha256sum -c aux.sha256
chmod 500 alsa-inspect pcm-transfer audio-session-guard
cd /
echo AUDIO_NEW_AUX_IN_RAM_NO_MODULE_OR_START
'''.replace('REMOTE', remote)
    (out / 'stage-aux.sh').write_text(stage)
    files['stage-aux.sh'] = out / 'stage-aux.sh'
    (out / 'aux.sha256').write_text(''.join(sha(path) + '  ' + name + '\n' for name, path in files.items() if name != 'boot-audio.img'))
    files['aux.sha256'] = out / 'aux.sha256'
    protected = [
        '0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28  /dev/block/by-name/boot',
        '4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e  /dev/block/by-name/uboot',
        'bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8  /dev/block/by-name/trust',
        '59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d  /dev/block/by-name/dtbo',
        '76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752  /dev/block/by-name/vbmeta',
        '4fcebae566d889072954b2f5b220474fe9accd75bbb48471023f24841b6ed95e  /cache/rtctrl-source-userspace-20261004/rootfs.ext4',
        '32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3  /cache/rtctrl-network-rootfs-20261004/rootfs.img',
    ]
    native = [
        '3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d  /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4',
        '54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef  /cache/rtctrl-pid1-20261005-v3/initramfs-pid1.cpio.gz',
        'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457  /cache/rtctrl-rcu-reset-20261004/Image',
    ]
    manifest = {'host_verified': True, 'mode': 'RAM_ONLY_NOT_FLASH_READY',
                'files': [{'name': name, 'source': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)} for name, path in files.items()],
                'protected_sha256': protected, 'native_cached_sha256': native,
                'package_audit_sha256': sha(audit), 'guard_manifest_sha256': args.guard_manifest_sha256,
                'builder_sha256': sha(Path(__file__)), 'board_tested': False, 'start_allowed': False}
    (out / 'input-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    def write(name, steps):
        (out / name).write_text(json.dumps(steps, indent=2) + '\n')

    def step(command, expect=None, wait=1):
        item = {'command': command, 'wait': wait}
        if expect:
            item['expect'] = expect
        return item

    write('load.json', [step('bdinfo', wait=2), step('printenv kernel_addr_r fdt_addr_r ramdisk_addr_r initrd_high fdt_high bootargs', wait=2),
          step('ext4load mmc 0:c 20000000 /rtctrl-audio-bootm-20261005-v1/boot-audio.img', '41943040 bytes read', 5),
          step('printenv filesize', r'filesize=0x2800000'), step('crc32 20000000 2800000', r'227fffff ==> fe7bd3a1', 3)])
    write('boot.json', [step('setenv initrd_high ffffffffffffffff'), step('setenv fdt_high ffffffffffffffff'),
          step('setenv kernel_addr_r 400000'), step('setenv ramdisk_addr_r 4000000'), step('setenv fdt_addr_r a100000'),
          step('printenv kernel_addr_r fdt_addr_r ramdisk_addr_r initrd_high fdt_high'),
          step('bootm 20000000', r'(?m)^LINUX_PID1_ROOT_READY\r?$', 45)])
    stage_steps = []
    data = stage.encode()
    stage_steps.append(step('test ! -e /tmp/audio-stage.sh && test ! -L /tmp/audio-stage.sh && echo AUDIO_STAGE_TARGET_ABSENT', 'AUDIO_STAGE_TARGET_ABSENT'))
    for offset in range(0, len(data), 96):
        encoded = ''.join('\\0' + f'{byte:03o}' for byte in data[offset:offset + 96])
        redirect = '>' if offset == 0 else '>>'
        stage_steps.append(step("printf '%b' '" + encoded + "' " + redirect + ' /tmp/audio-stage.sh', wait=0.05))
    stage_steps.append(step("test \"$(sha256sum /tmp/audio-stage.sh)\" = '" + sha(out / 'stage-aux.sh') + "  /tmp/audio-stage.sh' && sh /tmp/audio-stage.sh", r'(?m)^AUDIO_NEW_AUX_IN_RAM_NO_MODULE_OR_START\r?$', 5))
    write('copy-aux.json', stage_steps)
    semantic_path = ROOT / 'outputs/rk3568-boot-package-20261005/dt-semantics-v2.py'
    spec = importlib.util.spec_from_file_location('dt_semantic', semantic_path)
    semantic = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(semantic)
    tree = semantic.parse((HERE / 'build/audio-ram-shim-v1/applied-audit-only.dtb').read_bytes())
    keys = [key for key in tree['properties'] if (':dmas' in key or ':dma-names' in key or ':phandle' in key or ':status' in key or ':compatible' in key) and any(x in key for x in ('fe410000', 'fe550000', 'rk817-codec', 'rk809-sound'))]
    checks = []
    for key in sorted(keys):
        node, prop = key.rsplit(':', 1)
        path = '/proc/device-tree' + node + '/' + prop
        command = '''printf '%s\\n' "$(hexdump -v -e '1/1 "%02x"' ''' + path + ''')"'''
        checks.append(step(command, r'(?m)^' + tree['properties'][key] + r'\r?$', 1))
    write('live-audio-dt.json', checks)
    (out / 'live-audio-dt-expected.json').write_text(json.dumps({key: tree['properties'][key] for key in sorted(keys)}, indent=2) + '\n')
    print(json.dumps({'files': len(files), 'bytes': sum(x['bytes'] for x in manifest['files']), 'dt_properties': len(keys), 'input_manifest_sha256': sha(out / 'input-manifest.json')}))


if __name__ == '__main__':
    main()
