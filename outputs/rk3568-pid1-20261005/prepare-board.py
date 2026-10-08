#!/usr/bin/env python3
"""Freeze RAM-only PID1 board sessions; no communication or deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zlib
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRODUCTION = HERE / 'build/production-v1'
BB = ROOT / 'outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox'
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
PID_SHA = 'f24b86829560b963782b676d9f9a7c41cedab447587c2b6522489cedfb6f124c'
BB_SHA = '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1'


def sha(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('Ordinary input required: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def step(command, expect=None, wait=1):
    if any(ord(c) < 32 or ord(c) > 126 for c in command):
        raise ValueError('Serial command must be printable ASCII')
    return dict(command=command, wait=wait, **({'expect': expect} if expect else {}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--production', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r'v[1-9][0-9]*', value) for value in [args.revision, args.production]):
        parser.error('versions must be vN')
    if not re.fullmatch(r'[0-9a-f]{64}', args.manifest_sha256):
        parser.error('manifest SHA must be lowercase SHA256')
    production = HERE / 'build' / ('production-' + args.production)
    output = HERE / 'build' / ('board-' + args.revision)
    names = [name + '-' + args.revision + '.json' for name in
             ['pid1-load', 'pid1-boot', 'pid1-tests', 'pid1-shell', 'pid1-inspect',
              'pid1-exit-shell', 'pid1-return', 'pid1-ram-shell', 'pid1-return-check',
              'pid1-request-reboot', 'board-manifest']]
    for path in [output, *(HERE / name for name in names)]:
        if path.exists() or path.is_symlink():
            raise ValueError('Refusing overwrite: ' + str(path))
    manifest_path = production / 'manifest.json'
    if sha(manifest_path) != args.manifest_sha256:
        raise ValueError('Frozen production manifest changed')
    manifest = json.loads(manifest_path.read_text())
    pid_sha = manifest['artifacts']['pid1']['sha256']
    rootfs_path = manifest['cache_fixed_paths']['rootfs']
    if rootfs_path not in ['/cache/rtctrl-pid1-20261005/rootfs-pid1.ext4',
                           '/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4']:
        raise ValueError('Unreviewed fixed cache path')
    cache_directory = rootfs_path.rsplit('/', 1)[0]
    if ('cache=' + cache_directory + '\n') not in (HERE / 'prepare-android.sh').read_text():
        raise ValueError('Android preparation is not bound to the fixed production cache path')
    if pid_sha not in (HERE / 'linux-return-guard.sh').read_text():
        raise ValueError('Return guard not bound to this PID1 ELF')
    inputs = {'rootfs-pid1.ext4': production / 'rootfs-pid1.ext4',
              'initramfs-pid1.cpio.gz': production / 'initramfs-pid1.cpio.gz',
              'uart.dtb': ROOT / 'outputs/rk3568-motor-alignment-20261004/uart.dtb',
              'prepare-android.sh': HERE / 'prepare-android.sh'}
    records = {}
    for name in ['pid1', 'rootfs-pid1.ext4', 'initramfs-pid1.cpio.gz']:
        path = production / name
        record = manifest['artifacts'][name]
        if sha(path) != record['sha256'] or path.stat().st_size != record['bytes']:
            raise ValueError('Frozen production artifact changed: ' + name)
        records[name] = record
    if records['rootfs-pid1.ext4']['bytes'] != 16777216:
        raise ValueError('Read-only PID1 root image must remain 16 MiB')
    if not 0 < records['initramfs-pid1.cpio.gz']['bytes'] < 8 * 1024 * 1024:
        raise ValueError('Initrd outside the reviewed RAM span')
    image = ROOT / 'outputs/rk3568-rcu-reset-20261004/Image'
    if sha(image) != 'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457':
        raise ValueError('Cached Image host reference changed')
    data = image.read_bytes()
    offset, memory = struct.unpack_from('<QQ', data, 8)
    if data[56:60] != b'ARM\x64' or offset != 0 or memory != 35389440:
        raise ValueError('Image load span changed')
    records['Image'] = dict(sha256=sha(image), bytes=len(data), crc32=f'{zlib.crc32(data):08x}')
    dtb = inputs['uart.dtb']
    if sha(dtb) != '7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1' or dtb.stat().st_size != 162414:
        raise ValueError('Previously tested UART DTB changed')
    records['uart.dtb'] = dict(sha256=sha(dtb), bytes=dtb.stat().st_size, crc32=f'{zlib.crc32(dtb.read_bytes()):08x}')
    if sha(BB) != BB_SHA:
        raise ValueError('Exact BusyBox changed')
    applets = subprocess.check_output([str(QEMU), str(BB), '--list'], text=True).splitlines()
    if len(applets) != 52:
        raise ValueError('Exact applets changed')
    for name in ['linux-return-guard.sh']:
        subprocess.run([str(QEMU), str(BB), 'sh', '-n', str(HERE / name)], check=True)
    output.mkdir(parents=True)
    payload = output / 'payload'
    payload.mkdir()
    for name, path in inputs.items():
        shutil.copyfile(path, payload / name)
    checksums = {name: sha(payload / name) for name in inputs}
    (payload / 'upload.sha256').write_text(''.join(f'{digest}  {name}\n' for name, digest in checksums.items()))

    def write(name, value):
        (HERE / name).write_text(json.dumps(value, indent=2) + '\n')

    load = []
    for name, address, cache_path in [
        ('Image', 0x400000, '/rtctrl-rcu-reset-20261004/Image'),
        ('uart.dtb', 0x3000000, cache_directory[len('/cache'):] + '/uart.dtb'),
        ('initramfs-pid1.cpio.gz', 0x4000000, cache_directory[len('/cache'):] + '/initramfs-pid1.cpio.gz')
    ]:
        record = records[name]
        load += [step(f'ext4load mmc 0:c {address:x} {cache_path}', f"{record['bytes']} bytes read", 4),
                 step(f"crc32 {address:x} {record['bytes']:x}", '==> ' + record['crc32'])]
    load += [step('fdt addr 3000000'), step('fdt rsvmem print'),
             step('fdt print /reserved-memory', 'no-map')]
    write(names[0], load)
    boot = json.loads((ROOT / 'outputs/rk3568-cap1188-20261004/boot-ram.json').read_text())
    for row in boot:
        row['command'] = row['command'].replace('panic=10', 'panic=0')
    boot[-1] = step(f"booti 400000 4000000:{records['initramfs-pid1.cpio.gz']['bytes']:x} 3000000",
                    r'(?m)^LINUX_PID1_ROOT_READY\r?$', 40)
    write(names[1], boot)
    write(names[2], [step('codec', r'(?m)^SOFTWARE_TEST_PASSED path=/usr/bin/codec-test exit=0\r?$', 5),
                     step('pty', r'(?m)^SOFTWARE_TEST_PASSED path=/usr/bin/pty-test exit=0\r?$', 10)])
    write(names[3], [step('shell', 'pid1-rescue#', 3)])
    inspect = [step('cat /proc/1/mountinfo', wait=2), step('cat /proc/1/maps', wait=2),
               step('ls -l /proc/1/exe /proc/1/root /proc/1/fd', wait=2),
               step('test "$(sha256sum /proc/1/exe)" = ' + "'" + pid_sha + "  /proc/1/exe' && echo PID1_EXECUTABLE_SHA_VERIFIED", r'(?m)^PID1_EXECUTABLE_SHA_VERIFIED\r?$'),
               step('losetup -a', wait=2)]
    guard = (HERE / 'linux-return-guard.sh').read_bytes()
    guard_sha = hashlib.sha256(guard).hexdigest()
    inspect.append(step('test ! -e /tmp/pid1-return-guard.sh && test ! -L /tmp/pid1-return-guard.sh && echo PID1_RETURN_GUARD_PATH_ABSENT', r'(?m)^PID1_RETURN_GUARD_PATH_ABSENT\r?$'))
    for offset in range(0, len(guard), 96):
        chunk = guard[offset:offset + 96]
        encoded = ''.join('\\0' + f'{byte:03o}' for byte in chunk)
        decoded = subprocess.check_output([str(QEMU), str(BB), 'printf', '%b', encoded])
        if decoded != chunk:
            raise ValueError('Exact BusyBox octal round trip failed')
        inspect.append(step(f"printf '%b' '{encoded}' {'>' if offset == 0 else '>>'} /tmp/pid1-return-guard.sh", wait=0.05))
    inspect += [step(f'test "$(sha256sum /tmp/pid1-return-guard.sh)" = \'{guard_sha}  /tmp/pid1-return-guard.sh\' && echo PID1_RETURN_GUARD_SHA_VERIFIED', r'(?m)^PID1_RETURN_GUARD_SHA_VERIFIED\r?$'),
                step('test ! -e /tmp/normal-reboot && test ! -L /tmp/normal-reboot && cp /.backing-cache/rtctrl-normal-reboot-20261005-v1/normal-reboot /tmp/normal-reboot && test "$(sha256sum /tmp/normal-reboot)" = \'6c90fe3dca1f0ae6ffab50eddbfdccca27cc2f8ccf0821814456ae3980fe09f5  /tmp/normal-reboot\' && chmod 500 /tmp/normal-reboot && echo PID1_NORMAL_REBOOT_HELPER_IN_RAM', r'(?m)^PID1_NORMAL_REBOOT_HELPER_IN_RAM\r?$', 3)]
    write(names[4], inspect)
    write(names[5], [step('exit', r'(?m)^OWNED_SESSION_REAPED [^\r\n]*status=0\r?$', 3)])
    write(names[6], [step('return', r'(?m)^LINUX_PID1_RAM_READY_NO_RESET\r?$', 8),
                     step('status', r'(?m)^PID1_STATUS phase=4 [^\r\n]*backward=63 pivot=1 old_unmounted=1 loop_detached=1 cache_unmounted=1\r?$')])
    write(names[7], [step('shell', 'pid1-rescue#', 3)])
    write(names[8], [step(f'test "$(sha256sum /tmp/pid1-return-guard.sh)" = \'{guard_sha}  /tmp/pid1-return-guard.sh\' && sh /tmp/pid1-return-guard.sh', r'(?m)^PID1_INDEPENDENT_RAM_ONLY_RETURN_READY\r?$', 5), step('dmesg', wait=2)])
    write(names[9], [step(f'test "$(sha256sum /tmp/pid1-return-guard.sh)" = \'{guard_sha}  /tmp/pid1-return-guard.sh\' && sh /tmp/pid1-return-guard.sh && test "$(sha256sum /tmp/normal-reboot)" = \'6c90fe3dca1f0ae6ffab50eddbfdccca27cc2f8ccf0821814456ae3980fe09f5  /tmp/normal-reboot\' && /tmp/normal-reboot --request', r'Restarting system', 40)])
    write(names[10], dict(board_tested=False, deployment_performed=False,
                          production_manifest_sha256=sha(manifest_path), files=checksums,
                          upload_sha256=sha(payload / 'upload.sha256'), artifacts=records,
                          image_memory_bytes=memory, image_cached_path='/cache/rtctrl-rcu-reset-20261004/Image',
                          rootfs_path=rootfs_path,
                          payload=str(payload.relative_to(ROOT)), sessions={name: sha(HERE / name) for name in names[:-1]},
                          return_guard_sha256=guard_sha, generator_sha256=sha(Path(__file__))))
    print('PID1_BOARD_SESSIONS_PREPARED')


if __name__ == '__main__':
    main()
