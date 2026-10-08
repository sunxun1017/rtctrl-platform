#!/usr/bin/env python3
"""Verify complete host backups and prepare an exact ordinary-cache-file check."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'build/audio-reclaim-plan-v1'
FILES = [
    ('/cache/rtctrl-bootm-ram-20261005-v1/boot-original.img',
     'outputs/rk3568-backup-linux-20261003/original/boot.img', 41943040,
     '0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28'),
    ('/cache/rtctrl-pid1-20261005/rootfs-pid1.ext4',
     'outputs/rk3568-pid1-20261005/build/production-v2/rootfs-pid1.ext4', 16777216,
     '984fc6fd169df070001eb6c8a2c67908fc0813ec582ac75003670f592c0e556e'),
    ('/cache/rtctrl-pid1-20261005/initramfs-pid1.cpio.gz',
     'outputs/rk3568-pid1-20261005/build/production-v2/initramfs-pid1.cpio.gz', 971760,
     '43844135363491cd8faae69c1f62d8f85eff20593371f2343783953dc47cf2dd'),
]


def main():
    verified = []
    for device_path, relative, size, expected in FILES:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError('Ordinary complete backup required: ' + relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Host backup changed: ' + relative)
        verified.append({'device_path': device_path, 'host_backup': relative, 'bytes': size, 'sha256': expected})
    old = (ROOT / 'outputs/rk3568-bootm-ram-20261005/reclaim-candidate-v1-android.sh').read_text()
    # Retain the already exercised root/Android identity and protected checks,
    # replacing only the obsolete-file selection with these exact backed files.
    check_function = old[old.index('check_file()'):old.index('check_protected()')]
    protected = old[old.index('check_protected()'):old.index('test -d "$directory"')]
    protected = protected.replace('    check_file "$directory/boot-original.img" 41943040 0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28\n', '')
    # Also bind the currently successful v2 RAM package; do not reclaim it.
    protected = protected.replace('\n}\n', '\n    check_file /cache/rtctrl-bootm-ram-20261005-v1/boot-linux-ram-v2.img 41943040 67f351b822887c5e2fae10c099760a126d20daee2e9b2931b945a1176af37dbe\n}\n')
    script = '''#!/system/bin/sh
# Host backups must be freshly verified before this script is invoked.
set -eu
case "${1-}" in
    --check|--reclaim)
        action=$1
        ;;
    *)
        exit 2
        ;;
esac
test "$(id -u)" = 0
test "$(uname -r)" = 4.19.232
test "$(getprop ro.build.version.release)" = 11
test "$(getprop sys.boot_completed)" = 1
test "$(realpath /cache)" = /cache

'''
    script += check_function + protected
    script += '\n'.join(f'check_file {v["device_path"]} {v["bytes"]} {v["sha256"]}' for v in verified)
    script += '\ncheck_protected\ndf -k /cache\necho AUDIO_OLD_CACHE_BACKUPS_AND_PROTECTED_INPUTS_VERIFIED\n'
    script += '''
if test "$action" = --check; then
    exit 0
fi

'''
    for value in verified:
        script += 'rm -- ' + value['device_path'] + '\n'
        script += 'test ! -e ' + value['device_path'] + '\n'
        script += 'test ! -L ' + value['device_path'] + '\n'
    script += '\nsync\ncheck_protected\ndf -k /cache\necho AUDIO_EXACT_BACKED_CACHE_FILES_RECLAIMED\n'
    OUT.mkdir(parents=True, exist_ok=False)
    path = OUT / 'reclaim-android.sh'
    path.write_text(script)
    plan = {'files': verified, 'reclaim_bytes': sum(value['bytes'] for value in verified),
            'script_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'device_checked': False, 'device_reclaimed': False,
            'recursive_delete': False, 'partition_write': False}
    (OUT / 'host-backup-verification.json').write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps({'files': len(verified), 'bytes': plan['reclaim_bytes'], 'script_sha256': plan['script_sha256']}))


if __name__ == '__main__':
    main()
