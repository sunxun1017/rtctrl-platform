#!/usr/bin/env python3
"""Check real inputs and captures before recording bounded board results."""
import hashlib
import json
from pathlib import Path
import re

here = Path(__file__).resolve().parent
private = here / 'private'
repo = here.parents[1]


def read(name):
    return (private / name).read_text().replace('\r', '')


def require(condition, message):
    if not condition:
        raise ValueError(message)


inputs = json.loads((here / 'kernel-artifacts.json').read_text())
programs = json.loads((here / 'source-programs.json').read_text())
boot = read('boot-ram.raw.txt')
load = read('load-ram.raw.txt')
linux = read('linux-check.raw.txt')
returned = read('return-android.raw.txt')
android = read('android-final.raw.txt')
adb = read('adb-final-root.txt')
before = read('startup-before.txt')
network = read('android-network.raw.txt')
reset = returned.split('U-Boot SPL', 1)[0]
release = inputs['kernel_release']
for item in inputs['artifacts']:
    require(hashlib.sha256((here / item['file']).read_bytes()).hexdigest() == item['sha256'], item['file'])
    require(f"==> {item['crc32']}" in load, 'U-Boot load CRC missing: ' + item['file'])
require(hashlib.sha256((here / 'kernel.config').read_bytes()).hexdigest() == inputs['kernel_config_sha256'], 'Configuration changed')
for name, digest in inputs['patches'].items():
    path = repo / 'platforms/rk3568/boards/aiot-3568pq/patches' / name
    require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'Patch changed: ' + name)
for item in programs:
    require(hashlib.sha256((here / item['name']).read_bytes()).hexdigest() == item['sha256'], item['name'])
    require(item['name'] + ': OK' in linux, 'Program checksum was not checked')
require('RCU_RESET_KERNEL_BUILD_COMPLETE' in read('kernel-build.log'), 'Image build incomplete')
require(f'Linux version {release}' in boot and f'\n{release}\n' in linux, 'Source kernel not confirmed')
require('|/bin/sh./init.|' in linux, 'RAM PID1 not confirmed')
require('PARTNAME=cache' in linux and '/mnt/cache ext4 ro,relatime,norecovery' in linux, 'RO/noload cache phase missing')
for marker in ('PatchX codec:', 'PatchX POSIX PTY:', 'RCU_RESET_SOURCE_PROGRAMS_PASSED', 'RCU_RESET_RUNTIME_CHECK_DONE'):
    require(marker in linux, 'Source runtime check incomplete: ' + marker)
for marker in ('RAM_ONLY_STATE_CONFIRMED', 'NO_LOOP_REMAINS'):
    require(re.search(r'(?m)^' + marker + r'$', reset), 'Reset cleanup guard missing: ' + marker)
require('sysrq: Resetting' in reset and 'U-Boot 2017.09' in returned, 'SysRq/loader return missing')
require(not re.search(r'WARNING:|rcu_note_context_switch|Call trace:|Kernel panic|Oops:|BUG:', reset), 'Warning in Linux reset capture')
require(not re.search(r'WARNING:|Call trace:|Kernel panic|Oops:|BUG:', boot), 'Warning/trace in source boot capture')
for value in ('\n11\n', '\n1\n', '\n4.19.232\n', 'uid=0(root)', 'RCU_RESET_ANDROID_RETURN_CONFIRMED'):
    require(value in android, 'Final Android state missing: ' + value)
require('uid=0(root)' in adb, 'Final network ADB root check missing')
require(re.search(r'(?m)^7\s+4\s+1\s+7$', android), 'Final printk state missing')
hash_pattern = r'(?m)^([0-9a-f]{64})\s+/dev/block/by-name/(\w+)$'
old_hashes = {name: digest for digest, name in re.findall(hash_pattern, before)}
new_hashes = {name: digest for digest, name in re.findall(hash_pattern, android)}
require(set(new_hashes) == {'boot', 'uboot', 'trust', 'dtbo', 'vbmeta'}, 'Partition coverage mismatch')
require(new_hashes == old_hashes, 'Startup partition hashes changed')
require('5555' in network and 'LISTEN' in network and 'FAILED' in network and '100% packet loss' in network,
        'Initial link failure/ADB listening evidence missing')
sanitized = re.sub(r'\b(cpuid|cid|androidboot\.serialno)=[^\s]+', r'\1=<redacted>', linux)
(here / 'linux-runtime-check.txt').write_text(sanitized)
excerpt = [line for line in returned.splitlines() if (
    line in ('RAM_ONLY_STATE_CONFIRMED', 'NO_LOOP_REMAINS') or 'sysrq: Resetting' in line
    or line.startswith('U-Boot 2017.09') or 'Linux version 4.19.232' in line)]
excerpt = re.sub(r'\([^()]*@[^()]*\)', '(<builder>)', '\n'.join(excerpt))
(here / 'reset-excerpt.txt').write_text(excerpt + '\n')
result = {
    'date': '2026-10-04', 'board_kernel_boot_tested': True, 'deployable': False,
    'kernel_inputs': inputs, 'source_program_inputs': programs,
    'same_config_dtb_initramfs_as_previous_run': True,
    'ram_pid1_confirmed': True, 'linux_cache_readonly_noload': True,
    'source_codec_and_pty_passed': True, 'physical_uart_or_mcu_control_tested': False,
    'test_mounts_cleaned_before_reset': True, 'loop_guard_passed': True,
    'sysrq_reset_to_original_android_passed': True,
    'sysrq_rcu_warning_in_this_reset_capture': False,
    'sleep_branch_instrumented_on_board': False, 'board_reset_repetitions': 1,
    'normal_reboot_shutdown_lifecycle_validated': False,
    'all_boot_messages_warning_free': False,
    'long_term_stability_tested': False, 'realtime_latency_tested': False,
    'original_android_kernel': '4.19.232', 'original_android_boot_completed': True,
    'five_startup_partition_hashes_unchanged': True, 'startup_partition_sha256': new_hashes,
    'initial_adb_service_listening_but_gateway_neighbor_failed': True,
    'saved_wifi_disable_enable_performed': True,
    'adb_root_and_upload_recovered': True, 'final_network_adb_root_available_at_check': True,
    'wifi_long_term_stability_proven': False,
    'final_battery_level_percent': int(re.search(r'(?m)^\s*level: (\d+)$', android).group(1)),
    'final_external_power_reported': 'AC powered: true' in android or 'USB powered: true' in android,
    'printk_readback': [7, 4, 1, 7], 'serial_port_released': True,
    'flash_performed': False, 'saveenv_performed': False, 'motor_commands_sent': False,
    'raw_evidence_sha256': {name: hashlib.sha256((private / name).read_bytes()).hexdigest() for name in
        ('kernel-build.log', 'android-preflight.raw.txt', 'android-network.raw.txt', 'wifi-reconnect.raw.txt',
         'wifi-status.raw.txt', 'android-staging.txt', 'startup-before.txt', 'uboot-console.raw.txt',
         'load-ram.raw.txt', 'boot-ram.raw.txt', 'linux-check.raw.txt', 'return-android.raw.txt',
         'android-final.raw.txt', 'adb-final-root.txt')}
}
(here / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print('PASS: new Image loaded by CRC; source programs; RO/noload cleanup; SysRq return without RCU warning; 5 partition hashes; final Android/ADB root')
