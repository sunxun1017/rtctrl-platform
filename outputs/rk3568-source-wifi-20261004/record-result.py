#!/usr/bin/env python3
"""Bind final source/input hashes to actual board evidence, without credentials."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib

root = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
private = out / 'private'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return (private / name).read_text(errors='replace').replace('\r', '')


def marker(text, value):
    assert re.search(r'^' + re.escape(value) + r'$', text, re.M), value


def unpack_newc(data):
    offset = 0
    files = {}
    while data[offset:offset + 6] == b'070701':
        fields = [int(data[offset + 6 + 8*i:offset + 14 + 8*i], 16) for i in range(13)]
        offset += 110
        name = data[offset:offset + fields[11] - 1].decode()
        offset = (offset + fields[11] + 3) & ~3
        content = data[offset:offset + fields[6]]
        offset = (offset + fields[6] + 3) & ~3
        if name == 'TRAILER!!!':
            return files
        files[name] = content
    raise ValueError('Missing newc trailer')


inputs = json.loads((out / 'boot-inputs.json').read_text())
for name, path in {
    'Image': root / 'outputs/rk3568-rcu-reset-20261004/Image',
    'wifi.dtb': out / 'wifi.dtb',
    'initramfs-v5.cpio.gz': out / 'initramfs-v5.cpio.gz',
}.items():
    assert sha(path) == inputs[name]['sha256']
    assert path.stat().st_size == inputs[name]['bytes']

# The tested transfer optimization is two gzip/newc streams. Last entry wins.
remaining = (out / 'initramfs-v5.cpio.gz').read_bytes()
members = []
while remaining:
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    payload = decompressor.decompress(remaining) + decompressor.flush()
    assert decompressor.eof
    members.append(unpack_newc(payload))
    remaining = decompressor.unused_data
assert len(members) == 2
assert set(members[1]) == {'bin/network-helper'}
effective = members[0] | members[1]
for member, path in {
    'bin/network-helper': out / 'network-helper',
    'bin/wpa_supplicant': out / 'wpa_supplicant',
    'bin/wpa_cli': out / 'wpa_cli',
    'lib/modules/bcmdhd.ko': out / 'bcmdhd.ko',
    'etc/udhcpc.sh': out / 'dhcp-script.sh',
    'init': root / 'outputs/rk3568-source-userspace-20261004/ram-init.sh',
}.items():
    assert effective[member] == path.read_bytes(), member

baseline = read('android-baseline-final.raw.txt')
load = read('ram-load.raw.txt')
for name, expected in inputs.items():
    assert re.search(r'^crc32 for [^\n]+ ==> ' + expected['crc32'] + r'$', load, re.M), name
device = read('linux-wifi-device.raw.txt')
wpa = read('linux-wpa-normalized.raw.txt')
dhcp = read('linux-dhcp-transfer.raw.txt')
network = read('linux-network-final.raw.txt')
cleanup = read('linux-cleanup.raw.txt')
reset = read('return-android.raw.txt')
android = read('android-return-check.raw.txt')
host = read('final-host-verification.txt')
for expected in ['NETWORK_HELPER_QEMU_TESTS_PASSED', 'WIFI_DT_AUDIT_FAULTS_PASSED 12']:
    marker(host, expected)
assert 'SDIO_ID=02D0:A9BF' in device
assert 'DRIVER=bcmsdh_sdmmc' in device
assert 'actual 148500000HZ' in device
assert sha(out / 'network-helper') in device
assert sha(out / 'bcmdhd.ko') in device
assert 'version 7.45.96.150' in device + network
marker(wpa, 'wpa_state=COMPLETED')
marker(dhcp, 'DHCP_IPV4_CONFIGURED')
assert 'is alive!' in network
for expected in ['RAM_CREDENTIAL_REMOVED', 'WIFI_MODULE_UNLOADED',
                 'WIFI_TEST_PROCESSES_EXITED', 'WIFI_INTERFACE_REMOVED']:
    marker(cleanup, expected)
for expected in ['RAM_ONLY_STATE_CONFIRMED', 'NO_LOOP_REMAINS']:
    marker(reset, expected)
assert 'sysrq: Resetting' in reset
# Include the actual reset path after the SysRq announcement, before loader output.
loader = re.search(r'^DDR\s+\S+.*$', reset, re.M)
assert loader and loader.start() > reset.index('sysrq: Resetting')
linux_reset = reset[:loader.start()]
assert not re.search(r'Call trace:|Voluntary context switch within RCU|BUG:|Oops:', linux_reset)
marker(android, 'ANDROID_WIFI_BASELINE_COMPLETE')
assert 'uid=0(root)' in android
assert '4.19.232' in android
assert re.search(r'getprop ro\.build\.version\.release\n+11$', android, re.M)
assert re.search(r'getprop sys\.boot_completed\n+1$', android, re.M)
assert re.search(r'^7\s+4\s+1\s+7$', android, re.M)
assert re.search(r'^2$', android, re.M)
assert 'uid=0(root)' in read('adb-final-check.txt')

partition_names = ['boot', 'uboot', 'trust', 'dtbo', 'vbmeta']
partition_hashes = {}
for name in partition_names:
    pattern = r'^([0-9a-f]{64})\s+/dev/block/by-name/' + name + r'$'
    before = re.search(pattern, baseline, re.M)
    after = re.search(pattern, android, re.M)
    assert before and after and before[1] == after[1], name
    partition_hashes[name] = after[1]

firmware = {}
for name in ['fw_bcm43456c5_ag.bin', 'nvram_ap6256.txt']:
    data = effective['lib/firmware/' + name]
    digest = hashlib.sha256(data).hexdigest()
    assert digest in baseline and digest in device and digest in android
    firmware[name] = {'bytes': len(data), 'sha256': digest,
                      'role': 'firmware_binary' if name.endswith('.bin') else 'board_nvram_text',
                      'firmware_implementation_source_available': False if name.endswith('.bin') else None,
                      'redistribution_permission_verified': False}

assert not (out / 'transfer-result.json').exists(), 'Update board result after a successful roundtrip'
audit = json.loads((out / 'build/dtb-v3/audit.json').read_text())
assert audit['checks_passed'] == 90
kernel = root / 'third_party/linux-rk3588'
assert not subprocess.check_output(['git', '-C', str(kernel), 'status', '--porcelain'])
commit = subprocess.check_output(['git', '-C', str(kernel), 'rev-parse', 'HEAD'], text=True).strip()
assert commit == '9f9e9d18574d0914c0d192a90c3babfe1fd63c95'

sources = sorted(out.glob('*.py')) + sorted(out.glob('*.sh')) + [out / 'network-helper.c', out / 'transfer-client.ps1']
sources += [out / name for name in ['linux-cleanup.json', 'linux-wifi-device.json',
                                   'linux-wpa.json', 'linux-dhcp-transfer.json',
                                   'load-ram.json', 'boot-ram.json', 'return-android.json', 'wpa-build.config']]
board = root / 'platforms/rk3568/boards/aiot-3568pq'
sources += [board / name for name in ['bsp/rk3568-aiot-3568pq-wifi.dts', 'build-firstboot.py',
                                     'verify-wifi.py', 'test-wifi-audit.py']]
sources += sorted((board / 'patches').glob('000[1-4]-*.patch'))
source_hashes = {str(path.relative_to(root)): sha(path) for path in sources}

evidence_names = [
    'android-baseline-final.raw.txt', 'android-stage-final.raw.txt', 'stage-v5.raw.txt',
    'ram-load.raw.txt', 'ram-boot.raw.txt', 'linux-wifi-device.raw.txt',
    'linux-wpa-normalized.raw.txt', 'linux-dhcp-transfer.raw.txt',
    'linux-transfer-diagnose.raw.txt', 'linux-transfer-retry.raw.txt',
    'linux-network-final.raw.txt', 'linux-same-ap.raw.txt', 'linux-direct-24g.raw.txt',
    'linux-cleanup.raw.txt', 'return-android.raw.txt', 'android-return-check.raw.txt',
    'adb-final-check.txt', 'final-host-verification.txt',
]
result = {
    'date': '2026-10-04', 'phase': 'source-linux-wifi', 'overall_network_acceptance': 'partial',
    'kernel': {'commit': commit, 'release': '5.10.160-rt89-g9f9e9d18574d-dirty',
               'image_sha256': inputs['Image']['sha256'], 'source_restored_clean': True},
    'boot_inputs': inputs,
    'module': json.loads((out / 'module-check.json').read_text()) | {'board_loaded': True},
    'host_checks': {'dt_checks': 90, 'dt_faults_rejected': 12, 'helper_qemu_tests_passed': True},
    'board_network': {
        'sdio_id': '02D0:A9BF', 'sdio_controller': 'fe2c0000', 'sdio_bus_width': 4,
        'sdio_actual_hz': 148500000, 'firmware_version': '7.45.96.150',
        'wpa_version': '2.11', 'wpa2_psk_ccmp_completed': True,
        'dhcp_ipv4_route_dns_configured': True, 'gateway_icmp_reply': True,
        'windows_tcp_roundtrip_passed': False,
        'peer_arp_resolution_failed': True,
        'later_reassociation_failed': True, 'later_rssi_dbm': [-87, -86],
        'root_cause_confirmed': False, 'long_term_stability_tested': False,
        'wan_dns_tls_tested': False,
    },
    'firmware_binary_dependencies': firmware,
    'source_sha256': source_hashes,
    'effective_archive_sha256': {name: hashlib.sha256(data).hexdigest()
                                for name, data in effective.items() if data},
    'runtime_normalization': {
        'update_config_line_removed': True, 'wpa_log_uses_shell_redirection': True,
        'start_wifi_sh_packaged_in_tested_archive': False,
        'ram_credentials_removed': True, 'credentials_recorded_on_host': False,
    },
    'cleanup': {'wpa_and_transfer_exited': True, 'bcmdhd_unloaded': True,
                'wlan0_removed': True, 'ram_mounts_only': True, 'no_loop_remaining': True},
    'return_to_android': {
        'release': '11', 'kernel': '4.19.232', 'boot_completed': True, 'root_verified': True,
        'startup_partition_sha256_unchanged': partition_hashes,
        'printk': [7, 4, 1, 7], 'kptr_restrict': 2,
        'battery_level_percent': int(re.search(r'^\s*level: (\d+)$', android, re.M)[1]),
        'ac_powered': False, 'usb_powered': False, 'adb_root_verified_at_end': True,
    },
    'not_tested': ['normal_reboot', 'poweroff', 'mcu_or_motor_control', 'wifi_suspend',
                   'persistent_rootfs_autostart', 'internet_dns_tls', 'long_term_or_rt_performance'],
    'startup_partition_write_performed': False, 'uboot_saveenv_performed': False,
    'evidence_sha256_private_not_published': {name: sha(private / name) for name in evidence_names},
}
(out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
public_lines = [
    'Source Linux: ' + result['kernel']['release'],
    'SDIO_ID=02D0:A9BF; DRIVER=bcmsdh_sdmmc; actual clock=148500000 Hz',
    'Firmware=7.45.96.150; wpa_supplicant=v2.11',
    'Initial WPA2-PSK/CCMP: wpa_state=COMPLETED',
    'DHCP_IPV4_CONFIGURED; IPv4/default route/DNS address configured',
    'Gateway ICMP: alive reply observed',
    'Windows TCP roundtrip: NOT PASSED; peer ARP unresolved',
    'Later reconnection: ASSOCIATED then connection failure/disconnect, RSSI -87/-86 dBm; cause unconfirmed',
    'RAM_CREDENTIAL_REMOVED', 'WIFI_MODULE_UNLOADED', 'WIFI_TEST_PROCESSES_EXITED',
    'WIFI_INTERFACE_REMOVED', 'RAM_ONLY_STATE_CONFIRMED', 'NO_LOOP_REMAINS',
    'sysrq: Resetting (one source-Linux reset at uptime 945.701856 s)',
    'Android 11 / 4.19.232 / boot_completed=1 / uid=0(root)',
    'Startup SHA-256 unchanged: ' + ', '.join(partition_names),
    'printk=7/4/1/7; kptr_restrict=2; final battery=22%, AC/USB powered=false',
    'Final Android ADB root: verified at this check; not a stability guarantee',
    'NETWORK_HELPER_QEMU_TESTS_PASSED; DT checks=90; rejected faults=12',
]
(out / 'verification.txt').write_text('\n'.join(public_lines) + '\n')
print('SOURCE_WIFI_RESULT_RECORDED')
