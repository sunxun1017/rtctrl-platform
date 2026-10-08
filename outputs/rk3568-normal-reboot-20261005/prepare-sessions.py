#!/usr/bin/env python3
"""Bind normal reboot sessions to a tested helper and frozen display RAM guard."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_new(path, content):
    with path.open('x') as stream:
        json.dump(content, stream, indent=2)
        stream.write('\n')

def main():
    helper = HERE / 'build/production-v2/normal-reboot'
    production = json.loads((helper.parent / 'manifest.json').read_text())
    if sha(helper) != production['elf_sha256'] or sha(HERE / 'normal-reboot.c') != production['source_sha256']:
        raise ValueError('Production identity changed')
    display = ROOT / 'outputs/rk3568-display-20261005'
    manifest = json.loads((display / 'runtime-manifest-v2.json').read_text())
    guard = display / 'linux-return-guard.sh'
    if sha(guard) != manifest['files']['linux-return-guard.sh']:
        raise ValueError('Frozen display guard changed')
    busybox = ROOT / 'outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox'
    qemu = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
    applets = subprocess.check_output([str(qemu), str(busybox), '--list'], text=True).splitlines()
    if len(applets) != 52 or not {'chmod', 'cp', 'sha256sum', 'mount', 'umount'} <= set(applets):
        raise ValueError('Required target applets missing')
    source = HERE / 'linux-stage.sh'
    subprocess.run([str(qemu), str(busybox), 'sh', '-n', str(source)], check=True)
    steps = [{'command': 'test ! -e /tmp/normal-reboot-stage.sh && test ! -L /tmp/normal-reboot-stage.sh && echo NORMAL_REBOOT_STAGE_SCRIPT_ABSENT', 'expect': r'(?m)^NORMAL_REBOOT_STAGE_SCRIPT_ABSENT\r?$'}]
    data = source.read_bytes()
    for offset in range(0, len(data), 96):
        escaped = ''.join('\\0' + f'{b:03o}' for b in data[offset:offset+96])
        redirect = '>' if offset == 0 else '>>'
        steps.append({'command': f"printf '%b' '{escaped}' {redirect} /tmp/normal-reboot-stage.sh", 'wait': 0.05})
    steps.append({'command': 'test "$(sha256sum /tmp/normal-reboot-stage.sh)" = \'' + sha(source) + '  /tmp/normal-reboot-stage.sh\' && sh /tmp/normal-reboot-stage.sh && echo NORMAL_REBOOT_STAGE_EXIT_ZERO', 'expect': r'(?m)^NORMAL_REBOOT_STAGE_EXIT_ZERO\r?$', 'wait': 5})
    write_new(HERE / 'linux-stage-v1.json', steps)
    request = 'test "$(sha256sum /tmp/display-return-guard.sh)" = \'' + sha(guard) + '  /tmp/display-return-guard.sh\' && sh /tmp/display-return-guard.sh && test "$(sha256sum /tmp/normal-reboot)" = \'' + sha(helper) + '  /tmp/normal-reboot\' && /tmp/normal-reboot --request'
    write_new(HERE / 'linux-request-v1.json', [{'command': request, 'expect': r'(?m)^NORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN\r?$', 'wait': 40}])
    write_new(HERE / 'session-manifest-v1.json', {'helper_sha256': sha(helper), 'stage_sha256': sha(source), 'display_guard_sha256': sha(guard),
              'generator_sha256': sha(Path(__file__)), 'display_runtime_manifest_sha256': sha(display / 'runtime-manifest-v2.json'),
              'applet_count': len(applets), 'stage_session_sha256': sha(HERE / 'linux-stage-v1.json'),
              'request_session_sha256': sha(HERE / 'linux-request-v1.json'), 'normal_reboot_board_tested': False})
    print('NORMAL_REBOOT_SESSIONS_PREPARED_NO_HARDWARE')

if __name__ == '__main__':
    main()
