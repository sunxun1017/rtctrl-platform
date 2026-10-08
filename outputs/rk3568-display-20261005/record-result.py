#!/usr/bin/env python3
"""Record the captured zero-brightness interface and normal reboot round."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIVATE = HERE / 'private'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def section(record, name):
    value = record['sections'][name]
    if value['exit_code'] != 0:
        raise ValueError('Android read failed: ' + name)
    return value['output'].strip()

def marker(text, value):
    if not re.search(r'(?m)^' + re.escape(value) + r'\r?$', text):
        raise ValueError('Missing actual marker: ' + value)

def main():
    manifest = json.loads((HERE / 'runtime-manifest-v9.json').read_text())
    if sha(HERE / 'runtime-manifest-v9.json') != '83abd66250c10c58997b1b9ae42ffa55d077397aa75935713ce9e44b9086a924':
        raise ValueError('Frozen manifest changed')
    for name, digest in manifest['files'].items():
        if sha(ROOT / manifest['staging'] / name) != digest:
            raise ValueError('Frozen input changed: ' + name)
    for name, crc in [('Image', '6c3715bf'), ('display.dtb', '6ea18539'), ('initramfs.cpio.gz', '74fea1e6')]:
        if '==> ' + crc not in (PRIVATE / 'display-load-v9.raw.txt').read_text():
            raise ValueError('Actual U-Boot CRC missing: ' + name)
    before = json.loads((PRIVATE / 'android-before-display.json').read_text())
    after = json.loads((PRIVATE / 'android-after-display-normal-reboot.json').read_text())
    protected = {}
    for name in ['boot_sha256', 'uboot_sha256', 'trust_sha256', 'dtbo_sha256', 'vbmeta_sha256', 'source_rootfs_sha256', 'network_rootfs_sha256']:
        left, right = section(before, name), section(after, name)
        if left != right or not re.match(r'^[0-9a-f]{64}  /', left):
            raise ValueError('Protected input changed: ' + name)
        protected[name] = True
    for name, value in [('kernel', '4.19.232'), ('android', '11'), ('boot_completed', '1')]:
        if section(after, name) != value:
            raise ValueError('Android return not confirmed')
    stage = (PRIVATE / 'display-stage-v9.raw.txt').read_text()
    inspect = (PRIVATE / 'display-inspect-v9.raw.txt').read_text()
    boot = (PRIVATE / 'display-boot-v9.raw.txt').read_text()
    returned = (PRIVATE / 'normal-reboot-request-v1.raw.txt').read_text()
    for text, values in [(stage, ['DISPLAY_INPUTS_IN_RAM_CACHE_RELEASED', 'DISPLAY_STAGE_EXIT_ZERO']),
                         (inspect, ['DISPLAY_INTERFACE_METADATA_VERIFIED_AT_ZERO_BRIGHTNESS', 'DISPLAY_INSPECTION_EXIT_ZERO']),
                         (returned, ['DISPLAY_RAM_ONLY_RESET_READY', 'NORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN'])]:
        for value in values:
            marker(text, value)
    if 'panel initialization sequence completed (180 commands)' not in boot:
        raise ValueError('Full panel sequence diagnostic absent')
    tail = re.split(r'(?m)^NORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN\r?$', returned, maxsplit=1)[1].split('DDR ', 1)[0]
    restart = re.search(r'\[\s*([0-9.]+)\] reboot: Restarting system', tail)
    if not restart or 'Crtc atomic disable vp1' not in tail or re.search(r'WARNING:|BUG:|Call trace:|Kernel panic|Oops:', tail):
        raise ValueError('Normal reboot captured chain rejected')
    selected = json.loads((PRIVATE / 'runtime-selected-v1.json').read_text())
    values = selected['selected_readback']
    for name, value in [('drm-dsi-modes.txt', '720x720'), ('fb-geometry.txt', '720,720'),
                        ('fb-bpp.txt', '32'), ('fb-stride.txt', '2880'), ('backlight-brightness.txt', '0'),
                        ('backlight-actual.txt', '0')]:
        if values[name] != value:
            raise ValueError('Readback mismatch: ' + name)
    if 'period: 25000 ns duty: 0 ns' not in values['pwm.txt']:
        raise ValueError('PWM zero-duty identity absent')
    if sha(PRIVATE / 'display-live-fdt-v1.dtb') != selected['fdt_sha256']:
        raise ValueError('Complete captured FDT identity changed')
    evidence = ['android-before-display.json', 'android-after-display-normal-reboot.json', 'android-stage-v3.raw.txt',
                'uboot-display-v9.raw.txt', 'display-load-v9.raw.txt', 'display-boot-v9.raw.txt',
                'display-stage-v9.raw.txt', 'display-inspect-v9.raw.txt', 'normal-reboot-stage-v1.raw.txt',
                'normal-reboot-request-v1.raw.txt', 'display-live-fdt-v1.raw.txt', 'display-live-fdt-v2.raw.txt',
                'display-live-fdt-v3.raw.txt', 'display-live-fdt-v1.dtb', 'runtime-selected-v1.json']
    result = {'board_tested': True, 'image_sha256': manifest['files']['Image'], 'dtb_sha256': manifest['files']['display.dtb'],
              'initramfs_sha256': manifest['files']['initramfs.cpio.gz'], 'actual_sessions_revision': 'v9',
              'inspection_items_passed': selected['inspection_items_passed'], 'panel_host_sequence_commands_completed': 180,
              'panel_ack_or_physical_display_tested': False, 'physical_screen_connected': False,
              'drm_mode': '720x720', 'vop_port': 1, 'clock_hz': 35500000, 'fb_bits_per_pixel': 32, 'fb_stride': 2880,
              'backlight_brightness': 0, 'backlight_actual_brightness': 0, 'pwm_period_ns': 25000, 'pwm_duty_ns': 0,
              'pwm_enabled': True, 'brightness_write_performed': False, 'drm_or_fb_device_open_performed': False,
              'live_fdt_sha256': selected['fdt_sha256'], 'live_fdt_bytes': selected['fdt_bytes'],
              'fdt_transport_history': 'single long frame truncated; one 4KiB chunk lost 26 hex chars; reread four 1KiB chunks, full board SHA matched',
              'startup_diagnostics': ['expected loader memory skipped', 'two overlay Cluster win1 initialization messages',
                                      'pwm-backlight dummy regulator; no added guessed supply', 'inherited source BSP diagnostics retained'],
              'normal_reboot_tested': True, 'normal_reboot_restart_uptime_seconds': float(restart[1]),
              'normal_shutdown_to_first_DDR_warning_bug_calltrace_observed': False,
              'normal_reboot_helper_sha256': '6c90fe3dca1f0ae6ffab50eddbfdccca27cc2f8ccf0821814456ae3980fe09f5',
              'sysrq_used_for_this_return': False, 'android_return': '11 / 4.19.232 / boot_completed=1',
              'protected_sha256_unchanged': protected, 'battery_before_percent': int(re.search(r'level: (\d+)', section(before, 'battery'))[1]),
              'battery_after_percent': int(re.search(r'level: (\d+)', section(after, 'battery'))[1]),
              'private_evidence_sha256': {name: sha(PRIVATE / name) for name in evidence},
              'startup_partition_written': False, 'tun_settings_changed': False, 'poweroff_or_MCU_ACK_tested': False}
    (HERE / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    normal = ROOT / 'outputs/rk3568-normal-reboot-20261005'
    (normal / 'result.json').write_text(json.dumps({key: result[key] for key in [
        'normal_reboot_tested', 'normal_reboot_restart_uptime_seconds', 'normal_reboot_helper_sha256', 'image_sha256', 'dtb_sha256',
        'sysrq_used_for_this_return', 'android_return', 'protected_sha256_unchanged', 'battery_after_percent',
        'normal_shutdown_to_first_DDR_warning_bug_calltrace_observed', 'poweroff_or_MCU_ACK_tested', 'startup_partition_written', 'tun_settings_changed']}, indent=2) + '\n')
    print(json.dumps({'display_interface_passed': True, 'items': selected['inspection_items_passed'], 'normal_reboot_passed': True,
                      'protected_hashes_equal': 7, 'battery_after': result['battery_after_percent']}))

if __name__ == '__main__':
    main()
