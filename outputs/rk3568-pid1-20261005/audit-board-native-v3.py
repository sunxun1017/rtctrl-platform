#!/usr/bin/env python3
"""Summarize completed console evidence; performs no device operations."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if not out.is_relative_to(HERE / 'build') or out.exists():
        raise ValueError('Need fresh result directory inside own build')
    private = HERE / 'private'
    manifest_file = HERE / 'board-manifest-v4.json'
    assert digest(manifest_file) == '6b71dc13c70b869864d316245adcc436ec85ff8c7c63cadfba883a98dca253dd'
    manifest = json.loads(manifest_file.read_text())
    evidence = {}
    checks = []

    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})

    def raw(name):
        file = private / ('pid1-' + name + '-native-v3.raw.txt')
        evidence[str(file.relative_to(HERE))] = {'bytes': file.stat().st_size, 'sha256': digest(file)}
        return file.read_text().replace('\r', '')

    def line(text, expected):
        return expected in text.splitlines()

    load = raw('load')
    for label, size in [('Image', 34755072), ('uart.dtb', 162414), ('initramfs-pid1.cpio.gz', 972203)]:
        check(label + ' actual load bytes', str(size) + ' bytes read' in load)
        check(label + ' actual RAM CRC', '==> ' + manifest['artifacts'][label]['crc32'] in load)
    boot = raw('boot')
    check('native root READY', line(boot, 'LINUX_PID1_ROOT_READY'))
    check('real Linux 5.10 Image release', 'Linux version 5.10.160-rt89-g9f9e9d18574d-dirty' in boot)
    tests = raw('tests')
    for binary in ('codec-test', 'pty-test'):
        check(binary + ' exit zero', line(tests, 'SOFTWARE_TEST_PASSED path=/usr/bin/' + binary + ' exit=0'))
    check('two self-test children reaped', len(re.findall(r'^OWNED_SESSION_REAPED pid=\d+ start=\d+ status=0$', tests, re.M)) == 2)
    raw('shell')
    inspect = raw('inspect')
    check('actual loop root read-only', re.search(r'^\d+ \d+ 7:0 / / ro,[^\n]* - ext4 /dev/loop0 ro,norecovery$', inspect, re.M))
    check('actual cache read-only', re.search(r'^\d+ \d+ 179:12 / /\.backing-cache ro,[^\n]* - ext4 /dev/mmcblk0p12 ro,norecovery$', inspect, re.M))
    check('PID1 maps from loop inode45', re.search(r'^00400000-[^\n]*07:00 45 +/bin/pid1$', inspect, re.M))
    for marker in ('PID1_EXECUTABLE_SHA_VERIFIED', 'PID1_RETURN_GUARD_SHA_VERIFIED', 'PID1_NORMAL_REBOOT_HELPER_IN_RAM'):
        check(marker, line(inspect, marker))
    exited = raw('exit-shell')
    check('owned root shell reaped', re.search(r'^OWNED_SESSION_REAPED pid=\d+ start=\d+ status=0$', exited, re.M))
    returned = raw('return')
    check('native return completed', line(returned, 'LINUX_PID1_RAM_READY_NO_RESET'))
    check('all return ownership flags', re.search(r'^PID1_STATUS phase=4 [^\n]*backward=63 pivot=1 old_unmounted=1 loop_detached=1 cache_unmounted=1$', returned, re.M))
    raw('ram-shell')
    ram = raw('return-check')
    check('independent RAM guard', line(ram, 'PID1_INDEPENDENT_RAM_ONLY_RETURN_READY'))
    mount_lines = [s for s in ram.splitlines() if re.match(r'^(devtmpfs|proc|sysfs|tmpfs|devpts) /', s)]
    check('seven RAM-only mounts', len(mount_lines) == 7 and len({s.split()[1] for s in mount_lines}) == 7)
    check('no persistent mount in guard output', not any(' ext4 ' in s or '/dev/loop' in s for s in mount_lines))
    reboot = raw('request-reboot')
    check('reboot guard passed again', line(reboot, 'PID1_INDEPENDENT_RAM_ONLY_RETURN_READY'))
    check('ordinary syscall requested', line(reboot, 'NORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN'))
    restart = re.search(r'^\[\s*([0-9.]+)\] reboot: Restarting system$', reboot, re.M)
    check('ordinary reset reached', restart)
    request_offset = reboot.index('\nNORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN\n')
    ddr_offset = reboot.index('\nDDR ', request_offset)
    window = reboot[request_offset:ddr_offset]
    check('no severe diagnostics request to first DDR', not re.search(r'WARNING:|BUG:|Call trace:|Kernel panic', window))
    before_path = private / 'android-before-native-v3.json'
    after_path = private / 'android-after-native-v3.json'
    before, after = [json.loads(p.read_text()) for p in (before_path, after_path)]
    for p in (before_path, after_path):
        evidence[str(p.relative_to(HERE))] = {'bytes': p.stat().st_size, 'sha256': digest(p)}
    for name, expected in [('kernel', '4.19.232'), ('android', '11'), ('boot_completed', '1')]:
        section = after['sections'][name]
        check('fresh Android ' + name, section['exit_code'] == 0 and section['output'].strip() == expected)
    check('fresh Android root', after['sections']['root']['exit_code'] == 0 and after['sections']['root']['output'].startswith('uid=0(root)'))
    protected = {}
    for name in ('boot', 'uboot', 'trust', 'dtbo', 'vbmeta', 'source_rootfs', 'network_rootfs'):
        key = name + '_sha256'
        first, last = [record['sections'][key] for record in (before, after)]
        check(name + ' complete SHA unchanged', first['exit_code'] == last['exit_code'] == 0 and first['output'] == last['output'])
        protected[name] = last['output'].split()[0]
    battery = {phase: int(re.search(r'^\s*level: (\d+)$', record['sections']['battery']['output'], re.M).group(1))
               for phase, record in [('before', before), ('after', after)]}
    for filename, expected in manifest['sessions'].items():
        check('frozen ' + filename, digest(HERE / filename) == expected)
    result = {'schema': 1, 'native_version': 'production-v3', 'session_version': 'v4',
              'board_manifest_sha256': digest(manifest_file), 'checks': checks,
              'passed': sum(c['passed'] for c in checks), 'total': len(checks),
              'ordinary_restart_seconds': float(restart.group(1)) if restart else None,
              'battery_percent': battery, 'protected_sha256': protected, 'evidence': evidence,
              'manual_island_repair': False, 'manual_guard_repair': False,
              'flash_performed': False, 'full_emmc_diff': False, 'usb_recovery_confirmed': False,
              'scope': 'native PID1 root mount, pure software tests, native RAM return, normal reboot, Android 7-SHA comparison'}
    out.mkdir(parents=True, exist_ok=False)
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('passed', 'total', 'ordinary_restart_seconds', 'battery_percent')}))
    if result['passed'] != result['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
