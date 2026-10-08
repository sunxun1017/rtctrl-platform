#!/usr/bin/env python3
"""Bind actual original-package RAM bootm logs and fresh Android comparison."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PRIVATE = ROOT / 'outputs/rk3568-pid1-20261005/private'


def main():
    target = HERE / 'original-result-v2.json'
    if target.exists():
        raise ValueError('Refusing to overwrite evidence summary')
    evidence = {}
    checks = []

    def read(name):
        path = PRIVATE / name
        data = path.read_bytes()
        evidence[str(path.relative_to(ROOT))] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        return data.decode().replace('\r', '')

    def check(name, ok):
        checks.append({'name': name, 'passed': bool(ok)})

    fresh = read('uboot-before-original-bootm-v1.raw.txt')
    check('fresh RAM bank for package', '-> start    = 0x09400000' in fresh and '-> size     = 0xE6C00000' in fresh)
    check('fresh relocation/sp outside package', 'relocaddr   = 0xEDCF3000' in fresh and 'sp start    = 0xEB9F85B0' in fresh)
    load = read('original-bootm-load-v1.raw.txt')
    check('actual complete package load', '41943040 bytes read' in load)
    verified = read('original-bootm-loaded-verify-v2.raw.txt')
    check('actual filesize exact', 'filesize=0x2800000' in verified)
    check('actual full RAM CRC exact', 'crc32 for 20000000 ... 227fffff ==> 6e48ba06' in verified)
    boot = read('original-bootm-v1.raw.txt')
    check('single-address bootm', re.search(r'^(?:=> )?bootm 20000000$', boot, re.M))
    check('board Android RAM dispatch', 'BOOTM: transferring to board Android' in boot)
    check('RAM RSCE location', 'base: 0x2204e000' in boot and 'e_num:11' in boot)
    check('board-selected original resource DT', 'DTB: arch/arm64/boot/dts/rockchip/rk3568_smdt_3568a_v20.dtb' in boot)
    check('selected DT hash accepted', '\nHASH(c): OK\n' in boot)
    check('Android package hash accepted', '\nANDROID: Hash OK\n' in boot)
    check('actual kernel destination', 'Kernel: 0x00280000 - 0x02204008' in boot)
    check('actual ramdisk destination', 'ramdisk:    0x0a200000 - 0x0a2c8c20' in boot)
    check('actual FDT destination', 'Booting using the fdt blob at 0x0a100000' in boot)
    check('original Image kernel reached', 'Linux version 4.19.232' in boot)
    before = json.loads(read('android-before-original-bootm.json'))
    after = json.loads(read('android-after-original-bootm.json'))
    for name, expected in [('kernel', '4.19.232'), ('android', '11'), ('boot_completed', '1')]:
        section = after['sections'][name]
        check('fresh Android ' + name, section['exit_code'] == 0 and section['output'].strip() == expected)
    check('fresh Android root', after['sections']['root']['output'].startswith('uid=0(root)'))
    protected = {}
    for name in ('boot', 'uboot', 'trust', 'dtbo', 'vbmeta', 'source_rootfs', 'network_rootfs'):
        first, last = [record['sections'][name + '_sha256'] for record in (before, after)]
        check(name + ' full SHA unchanged', first['exit_code'] == last['exit_code'] == 0 and first['output'] == last['output'])
        protected[name] = last['output'].split()[0]
    battery = {phase: int(re.search(r'^\s*level: (\d+)$', record['sections']['battery']['output'], re.M).group(1))
               for phase, record in [('before', before), ('after', after)]}
    result = {'schema': 1, 'mode': 'ORIGINAL_PACKAGE_RAM_BOOTM_ONLY', 'checks': checks,
              'passed': sum(c['passed'] for c in checks), 'total': len(checks), 'evidence': evidence,
              'package_interval': [0x20000000, 0x22800000], 'battery_percent': battery,
              'protected_sha256': protected, 'header_addresses_used_as_destinations': False,
              'cli_reachable_conditional_boot_verified': True, 'boot_partition_write': False,
              'saveenv': False, 'bare_metal_recovery_verified': False, 'usb_recovery_confirmed': False,
              'linux_candidate_board_tested': False,
              'load_v1_rejected_reason': 'expected filesize without 0x; actual exact 0x2800000 checked by new v2 session before CRC and bootm',
              'summary_v1_rejected_reason': 'actual console echoed => bootm 20000000 on same line; v2 checks exact command with optional prompt prefix'}
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('passed', 'total', 'battery_percent')}))
    if result['passed'] != result['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
