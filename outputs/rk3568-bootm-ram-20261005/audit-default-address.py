#!/usr/bin/env python3
"""Audit the actual default-destination trial; no inferred full-tree pass."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PRIVATE = HERE.parent / 'rk3568-pid1-20261005/private'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw(name):
    # Preserve solitary CR used for console cursor movement.
    return (PRIVATE / name).read_bytes().decode('ascii').replace('\r\n', '\n')


def bootm_requests(console):
    return len(re.findall(r'(?m)^(?:=> )?bootm 20000000\r?$', console))


def main():
    out = HERE / 'default-address-result-v2.json'
    if out.exists():
        raise ValueError('Fresh result required')
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)

    before_path = PRIVATE / 'android-before-default-address-v1.json'
    before = json.loads(before_path.read_text())
    check('fresh_preflight_accepted', before.get('accepted') is True)
    check('fresh_preflight_read_only', before['read_only'] and not before['partition_write'])
    package = REPO / 'outputs/rk3568-boot-package-20261005/build/ram-candidate-v2/boot-padded.img'
    check('complete_host_package_sha', package.stat().st_size == 41943040 and sha(package) == '67f351b822887c5e2fae10c099760a126d20daee2e9b2931b945a1176af37dbe')
    load = raw('default-address-load-v1.raw.txt')
    boot = raw('default-address-boot-v1.raw.txt')
    check('fresh_default_addresses', all(x in load for x in ('kernel_addr_r=0x00280000', 'fdt_addr_r=0x0a100000', 'ramdisk_addr_r=0x0a200000')))
    check('fresh_gd_matches_fdt', 'fdt_blob = 000000000a100000' in load)
    check('fresh_dram_banks', all(x in load for x in ('-> start    = 0x00200000', '-> size     = 0x08200000', '-> start    = 0x09400000', '-> size     = 0xE6C00000')))
    check('fresh_reloc_and_stack', '0xEDCF3000' in load and '0xEB9F85B0' in load)
    check('complete_board_load_and_crc', '41943040 bytes read' in load and '227fffff ==> cab15fb2' in load)
    commands = json.loads((HERE / 'default-address-boot-v1.json').read_text())
    check('no_manual_bootargs_or_destination_override', all(not x['command'].startswith(('setenv bootargs', 'setenv kernel_addr_r', 'setenv fdt_addr_r', 'setenv ramdisk_addr_r')) for x in commands))
    check('temporary_high_limits_recorded', 'initrd_high=ffffffffffffffff' in boot and 'fdt_high=ffffffffffffffff' in boot)
    check('one_bootm', bootm_requests(boot) == 1)
    check('one_dt_selection', len(re.findall(r'(?m)^DTB: .*rk3568_smdt_3568a_v20\.dtb\r?$', boot)) == 1)
    check('one_resource_dt_read', boot.count('<rockchip_read_dtb_file for kernel>') == 1)
    check('one_overlay_ok', boot.count('ANDROID: fdt overlay OK') == 1)
    check('both_component_hashes_ok', 'HASH(c): OK' in boot and 'ANDROID: Hash OK' in boot)
    check('no_duplicate_fdt_dtbo_allocation', not re.search(r'(?:FDT_DTBO|DTB).*already exist|DTB.*for existence', boot))
    check('default_kernel_source_span', 'Kernel: 0x00280000 - 0x023a5200' in boot)
    check('actual_overlap_relocation', boot.count('== DO RELOCATE == Kernel from 0x00280000 to 0x00200000') == 1)
    check('default_initrd_span', 'ramdisk:    0x0a200000 - 0x0a2ed5ab' in boot)
    check('fdt_kept_in_place', 'Using Device Tree in place at 000000000a100000' in boot)
    check('native_root_ready', bool(re.search(r'(?m)^LINUX_PID1_ROOT_READY\r?$', boot)))
    meta = raw('default-address-linux-meta-v1.raw.txt')
    lines = re.findall(r'(?m)^storagemedia=emmc androidboot\.storagemedia=emmc[^\n]*', meta)
    check('one_live_cmdline', len(lines) == 1)
    cmdline = lines[0].strip() if len(lines) == 1 else ''
    required = 'console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init ro loglevel=7 panic=0'
    check('package_linux_cmdline_reached_kernel', required in cmdline)
    check('original_environment_metadata_retained', all(x in cmdline for x in ('androidboot.mode=normal', 'androidboot.dtb_idx=0', 'androidboot.dtbo_idx=0')))
    check('chosen_overlay_bootargs_ext_retained', 'androidboot.boot_devices=fe310000.sdhci,fe330000.nandc' in cmdline)
    fdt = re.findall(r'(?m)^DEFAULT_FDT_META_BEGIN\r?\n(\d+)\r?\n([0-9a-f]{64})  /tmp/default-live\.dtb\r?\nDEFAULT_FDT_META_END\r?$', meta)
    check('one_full_fdt_size_sha_witness', len(fdt) == 1 and fdt[0] == ('168064', 'aeed58e22a00e92b496b36fb1fb386a7bba7414e0d4bb07efc9cf9656092178a'))
    chosen = '616e64726f6964626f6f742e626f6f745f646576696365733d66653331303030302e73646863692c66653333303030302e6e616e646300\n000000000a200000\n000000000a2ed5ab\n000002f9'
    check('chosen_initrd_and_phandle_witness', chosen in meta.replace('\r', ''))
    check('chosen_mode_witness', '5242c300\n5242c309\n5242c303' in meta.replace('\r', ''))
    inspect = raw('default-address-pid1-inspect-v1.raw.txt')
    check('native_pid1_actual_file_and_sha', 'PID1_EXECUTABLE_SHA_VERIFIED' in inspect and bool(re.search(r'(?m)^00400000-00499000 r-xp 00000000 07:00 45 +/bin/pid1\r?$', inspect)))
    check('readonly_root_and_cache', 'ext4 /dev/loop0 ro,norecovery' in inspect and 'ext4 /dev/mmcblk0p12 ro,norecovery' in inspect)
    check('unchanged_ram_guard_and_reboot_helper', 'PID1_RETURN_GUARD_SHA_VERIFIED' in inspect and 'PID1_NORMAL_REBOOT_HELPER_IN_RAM' in inspect)
    tests = raw('default-address-pid1-tests-v1.raw.txt')
    for label in ('codec', 'pty'):
        check(label + '_selftest_exit0_reaped', f'SOFTWARE_TEST_PASSED path=/usr/bin/{label}-test exit=0' in tests and len(re.findall(r'(?m)^OWNED_SESSION_REAPED .*status=0\r?$', tests)) == 2)
    returned = raw('default-address-pid1-return-v1.raw.txt')
    check('native_ram_return_complete', 'LINUX_PID1_RAM_READY_NO_RESET' in returned and 'backward=63 pivot=1 old_unmounted=1 loop_detached=1 cache_unmounted=1' in returned)
    check('independent_ram_guard_passed', bool(re.search(r'(?m)^PID1_INDEPENDENT_RAM_ONLY_RETURN_READY\r?$', raw('default-address-pid1-return-check-v1.raw.txt'))))
    restart = raw('default-address-pid1-request-reboot-v1.raw.txt')
    check('ordinary_reboot_requested', 'NORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN' in restart)
    check('ordinary_restart_then_ddr', bool(re.search(r'reboot: Restarting system\nDDR ', restart)))
    window = restart.split('NORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN', 1)[-1].split('\nDDR ', 1)[0]
    check('request_to_first_ddr_no_severe_diagnostics', not re.search(r'WARNING:|BUG:|Call trace:|Kernel panic', window))
    after = raw('default-address-android-after-v1.raw.txt')
    after_steps = json.loads((HERE / 'default-address-android-after-v1.json').read_text())
    for i, step in enumerate(after_steps[:11]):
        check('android_after_' + ('root', 'kernel', 'version', 'ready', 'boot', 'uboot', 'trust', 'dtbo', 'vbmeta', 'source_rootfs', 'network_rootfs')[i], len(re.findall(step['expect'], after)) == 1)
    levels = re.findall(r'(?m)^\s*level: (\d+)\s*$', after)
    check('fresh_battery_field', len(levels) == 1)
    input_paths = [before_path, package, Path(__file__), HERE / 'DEFAULT-ADDRESS-PLAN.md', HERE / 'prepare-default-address-trial.ps1']
    input_paths += list(HERE.glob('default-address-*.json'))
    input_paths += list(PRIVATE.glob('default-address-*.raw.txt'))
    input_paths += [PRIVATE / 'uboot-before-default-address-v1.raw.txt']
    input_paths += [HERE / 'build/audit-sources/audit-default-address-v1.py', HERE / 'test-default-address-audit.py']
    input_paths += [HERE.parent / 'rk3568-pid1-20261005' / name for name in ('pid1-shell-v4.json', 'pid1-inspect-v4.json', 'pid1-exit-shell-v4.json', 'pid1-tests-v4.json', 'pid1-return-v4.json', 'pid1-ram-shell-v4.json', 'pid1-return-check-v4.json', 'pid1-request-reboot-v4.json')]
    result = {
        'passed': all(checks.values()), 'checks_passed': sum(checks.values()), 'checks_total': len(checks),
        'checks': checks, 'default_kernel_relocated_to': '0x00200000', 'kernel_header_image_size': 35389440,
        'effective_kernel_memory_end': '0x023c0000', 'manual_bootargs_override': False,
        'temporary_initrd_high_and_fdt_high': True, 'full_fdt_size': 168064,
        'full_fdt_sha256_witness': 'aeed58e22a00e92b496b36fb1fb386a7bba7414e0d4bb07efc9cf9656092178a',
        'full_live_fdt_exported': False, 'full_live_fdt_semantic_audit': False,
        'chosen_subset_readback_verified': checks['chosen_initrd_and_phandle_witness'] and checks['chosen_mode_witness'],
        'early_new_dtb_dm_tested': False, 'formal_partition_boot_tested': False, 'usb_recovery_tested': False,
        'flash_ready': False, 'saveenv': False, 'partition_write': False,
        'supersedes_audit_result': 'default-address-result-v1.json',
        'audit_v1_source_preserved_at': 'build/audit-sources/audit-default-address-v1.py',
        'audit_correction': 'Recognize the actual U-Boot => prompt before a complete bootm command line; rejected v1 result retained.',
        'restart_kernel_timestamp_seconds': 469.421803,
        'battery_before_percent': int(re.search(r'(?m)^\s*level: (\d+)\s*$', before['sections']['battery']['output'])[1]),
        'battery_after_percent': int(levels[0]) if len(levels) == 1 else None,
        'files_sha256': {p.relative_to(REPO).as_posix(): sha(p) for p in input_paths},
    }
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('passed', 'checks_passed', 'checks_total', 'battery_before_percent', 'battery_after_percent', 'full_live_fdt_semantic_audit')}))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
