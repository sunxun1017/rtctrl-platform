#!/usr/bin/env python3
"""Check saved RAM bootm evidence; does not operate the board or approve flash."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
PRIVATE = HERE.parent / 'rk3568-pid1-20261005/private'
PACKAGE = HERE.parent / 'rk3568-boot-package-20261005'
PID1 = HERE.parent / 'rk3568-pid1-20261005'
PARSER_SHA = 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56'
PACKAGE_SHA = '67f351b822887c5e2fae10c099760a126d20daee2e9b2931b945a1176af37dbe'
PID1_MANIFEST_SHA = '6b71dc13c70b869864d316245adcc436ec85ff8c7c63cadfba883a98dca253dd'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=int, choices=(2, 3), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--semantic-review', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.parent != HERE or out.exists():
        raise ValueError('Fresh result filename inside own directory required')
    evidence, checks = {}, []

    def bind(path):
        evidence[str(path.relative_to(HERE.parent))] = {
            'bytes': path.stat().st_size, 'sha256': digest(path),
        }
        return path

    def raw(name):
        path = bind(PRIVATE / (name + f'-v{args.trial}.raw.txt'))
        return path.read_bytes().decode('ascii').replace('\r\n', '\n')

    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})

    def line(text, value):
        return value in text.split('\n')

    manifest_path = bind(PID1 / 'board-manifest-v4.json')
    check('frozen PID1 session manifest', digest(manifest_path) == PID1_MANIFEST_SHA)
    manifest = json.loads(manifest_path.read_text())
    for filename, expected in manifest['sessions'].items():
        check('frozen ' + filename, digest(bind(PID1 / filename)) == expected)
    check('same frozen v2 package', digest(bind(PACKAGE / 'build/ram-candidate-v2/boot-padded.img')) == PACKAGE_SHA)

    fresh = raw('uboot-before-linux-bootm')
    for marker in ('-> start    = 0x00200000', '-> size     = 0x08200000',
                   '-> start    = 0x09400000', '-> size     = 0xE6C00000',
                   'relocaddr   = 0xEDCF3000', 'sp start    = 0xEB9F85B0',
                   'fdt_blob = 000000000a100000'):
        check('fresh ' + marker.split(' = ')[0], line(fresh, marker))
    load = raw('linux-candidate-load')
    for marker in ('41943040 bytes read', 'filesize=0x2800000',
                   'crc32 for 20000000 ... 227fffff ==> cab15fb2'):
        check('load ' + marker, marker in load)
    boot = raw('linux-candidate-boot')
    check('single bootm command', len(re.findall(r'^(?:=> )?bootm 20000000$', boot, re.M)) == 1)
    for marker in ('BOOTM: transferring to board Android', 'HASH(c): OK',
                   'ANDROID: fdt overlay OK', 'ANDROID: Hash OK',
                   'Kernel: 0x00400000 - 0x02525200',
                   'ramdisk:    0x04000000 - 0x040ed5ab',
                   'Linux version 5.10.160-rt89-g9f9e9d18574d-dirty'):
        check('actual ' + marker, marker in boot)
    address = '0x03000000' if args.trial == 2 else '0x0a100000'
    check('actual FDT destination', '## Flattened Device Tree blob at ' + address in boot)
    check('exact one selected resource DT', len(re.findall(r'^DTB: ', boot, re.M)) == 1)
    check('no repeated FDT_DTBO allocation', not re.search(r'Failed to double alloc[^\n]*FDT_DTBO', boot))
    check('native ROOT_READY', line(boot, 'LINUX_PID1_ROOT_READY'))
    tests = raw('linux-bootm-pid1-tests')
    for binary in ('codec-test', 'pty-test'):
        check(binary + ' exit0', line(tests, f'SOFTWARE_TEST_PASSED path=/usr/bin/{binary} exit=0'))
    check('two test children reaped', len(re.findall(r'^OWNED_SESSION_REAPED pid=\d+ start=\d+ status=0$', tests, re.M)) == 2)
    raw('linux-bootm-pid1-shell')
    inspect = raw('linux-bootm-pid1-inspect')
    check('actual read-only loop root', re.search(r'^\d+ \d+ 7:0 / / ro,[^\n]* - ext4 /dev/loop0 ro,norecovery$', inspect, re.M))
    check('actual read-only cache', re.search(r'^\d+ \d+ 179:12 / /\.backing-cache ro,[^\n]* - ext4 /dev/mmcblk0p12 ro,norecovery$', inspect, re.M))
    check('PID1 executable loop inode45', re.search(r'^00400000-[^\n]*07:00 45 +/bin/pid1$', inspect, re.M))
    for marker in ('PID1_EXECUTABLE_SHA_VERIFIED', 'PID1_RETURN_GUARD_SHA_VERIFIED', 'PID1_NORMAL_REBOOT_HELPER_IN_RAM'):
        check(marker, line(inspect, marker))
    exited = raw('linux-bootm-pid1-exit-shell')
    check('root shell reaped', re.search(r'^OWNED_SESSION_REAPED pid=\d+ start=\d+ status=0$', exited, re.M))
    returned = raw('linux-bootm-pid1-return')
    check('native RAM return', line(returned, 'LINUX_PID1_RAM_READY_NO_RESET'))
    check('all ownership flags returned', re.search(r'^PID1_STATUS phase=4 [^\n]*backward=63 pivot=1 old_unmounted=1 loop_detached=1 cache_unmounted=1$', returned, re.M))
    raw('linux-bootm-pid1-ram-shell')
    ram = raw('linux-bootm-pid1-return-check')
    check('independent RAM guard', line(ram, 'PID1_INDEPENDENT_RAM_ONLY_RETURN_READY'))
    mounts = [s for s in ram.split('\n') if re.match(r'^(devtmpfs|proc|sysfs|tmpfs|devpts) /', s)]
    check('seven unique RAM mounts', len(mounts) == 7 and len({s.split()[1] for s in mounts}) == 7)
    check('no persistent mounts in guard output', not any(' ext4 ' in s or '/dev/loop' in s for s in mounts))
    reboot = raw('linux-bootm-pid1-request-reboot')
    check('reboot independent guard', line(reboot, 'PID1_INDEPENDENT_RAM_ONLY_RETURN_READY'))
    check('ordinary reboot request', line(reboot, 'NORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN'))
    restart = re.search(r'^\[\s*([0-9.]+)\] reboot: Restarting system$', reboot, re.M)
    check('ordinary reset reached', restart)
    request = reboot.index('\nNORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN\n')
    ddr = reboot.index('\nDDR ', request)
    check('no severe diagnostic request to DDR', not re.search(r'WARNING:|BUG:|Call trace:|Kernel panic', reboot[request:ddr]))

    before_file = PRIVATE / ('android-before-linux-bootm-v2.json' if args.trial == 2 else 'android-after-linux-bootm-v2-serial.json')
    after_file = PRIVATE / f'android-after-linux-bootm-v{args.trial}-serial.json'
    before, after = [json.loads(bind(p).read_text()) for p in (before_file, after_file)]
    check('fresh after UART capture', after['success'] and after['transport'] == 'UART' and
          digest(bind(PRIVATE / f'android-baseline-after-linux-bootm-v{args.trial}.raw.txt')) == after['raw_sha256'])
    for name, expected in (('kernel', '4.19.232'), ('android', '11'), ('boot_completed', '1')):
        check('fresh Android ' + name, after['sections'][name]['output'].strip() == expected)
    check('fresh Android root', after['sections']['root']['output'].startswith('uid=0(root)'))
    for name in ('boot', 'uboot', 'trust', 'dtbo', 'vbmeta', 'source_rootfs', 'network_rootfs'):
        key = name + '_sha256'
        check(name + ' full SHA unchanged', before['sections'][key]['output'].strip() == after['sections'][key]['output'].strip())
    battery = {phase: int(re.search(r'^\s*level: (\d+)$', record['sections']['battery']['output'], re.M)[1])
               for phase, record in (('before', before), ('after', after))}

    source = bind(PACKAGE / 'dt-semantics-v2.py')
    if digest(source) != PARSER_SHA:
        raise ValueError('FDT parser changed')
    spec = importlib.util.spec_from_file_location('semantics', source)
    semantics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(semantics)
    live_path = bind(PRIVATE / f'linux-bootm-live-v{args.trial}.dtb')
    tree = semantics.parse(live_path.read_bytes())
    semantics.phandles(tree)
    properties = tree['properties']
    expected_overlay = {
        '/chosen:bootargs_ext': b'androidboot.boot_devices=fe310000.sdhci,fe330000.nandc\0'.hex(),
        '/reboot-mode:mode-bootloader': '5242c309',
        '/reboot-mode:mode-fastboot': '5242c303',
        '/reboot-mode:mode-normal': '5242c300',
    }
    # Resolve the exact reboot-mode node, rather than assuming a top-level path.
    for key, value in expected_overlay.items():
        suffix = ':' + key.split(':')[1]
        matches = [p for p in properties if p.endswith(suffix)]
        check('final overlay ' + key.split(':')[1], len(matches) == 1 and properties[matches[0]] == value)
    transfer = json.loads(bind(HERE / f'live-fdt-transfer-v{args.trial}.json').read_text())
    metadata_raw = bind(PRIVATE / f'linux-bootm-live-fdt-meta-v{args.trial}.raw.txt')
    read_suffix = '-256' if args.trial == 3 else ''
    transfer_raw = bind(PRIVATE / f'linux-bootm-live-fdt-read-v{args.trial}{read_suffix}.raw.txt')
    check('full FDT transfer receipt', transfer['sha256'] == digest(live_path) and
          transfer['bytes'] == live_path.stat().st_size and transfer['board_sha_matches_reconstruction'] and
          transfer['metadata_raw_sha256'] == digest(metadata_raw) and transfer['read_raw_sha256'] == digest(transfer_raw))
    review = json.loads(bind(args.semantic_review.resolve()).read_text()) if args.semantic_review else {}
    check('complete final FDT semantic review', review.get('live_sha256') == digest(live_path) and
          review.get('semantic_review_completed') is True and review.get('accepted') is True)
    own_source = Path(__file__).resolve()
    snapshot = HERE / 'build/audit-sources' / (digest(own_source) + '.py')
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.exists():
        if snapshot.read_bytes() != own_source.read_bytes():
            raise ValueError('Auditor snapshot changed')
    else:
        with snapshot.open('xb') as stream:
            stream.write(own_source.read_bytes())
    bind(snapshot)
    result = {
        'schema': 1, 'mode': 'LINUX_PACKAGE_RAM_BOOTM_ONLY', 'package_version': 'v2',
        'trial': args.trial, 'checks': checks, 'passed': sum(c['passed'] for c in checks),
        'total': len(checks), 'evidence': evidence, 'battery_percent': battery,
        'ordinary_restart_seconds': float(restart[1]) if restart else None,
        'manual_island_repair': False, 'manual_guard_repair': False, 'flash_performed': False,
        'full_emmc_diff': False, 'usb_recovery_confirmed': False,
    }
    with out.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: result[key] for key in ('trial', 'passed', 'total', 'ordinary_restart_seconds', 'battery_percent')}))
    if result['passed'] != result['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
