#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Construct a separate offline software candidate; no board or flash operation."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
from types import SimpleNamespace
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PACKAGE = 'outputs/rk3568-boot-package-20261005/'
AUDIO = 'outputs/rk3568-audio-runtime-20261005/'
CPU = '/i2s@fe410000'
CODEC = '/i2c@fdd40000/pmic@20/codec'
CARD = '/rk809-sound'
FLAG = 'rockchip,checked-shared-params-48k'
SIZE = 40 * 1024 * 1024
CMDLINE = 'console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init ro loglevel=7 panic=0'
MODE = 'OFFLINE_NEW_AUDIO_SOFTWARE_CANDIDATE_NOT_BOARD_ACCEPTED'
DEPENDENCIES = {
    'audit-boot.py': (15327, '4902a1281665d58f7e053838af5547522cc6f227c2be1baf6d260cf2ccd6067d'),
    'build-roundtrip.py': (8679, 'b485eaf390799c9af2de2b25e5a79c77db3b368de0e5784c6b08c620492b18fc'),
    'build-ram-candidate-v2.py': (11504, '298c0c6620ad0703d5566b233176cd276b0404e589d94152c9ae809ddb7eae1d'),
    'dt-semantics-v2.py': (5164, 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56'),
    'libfdt-v2.py': (5537, '9fdba61ae8d7d004ac7f24b7f116f6a314032c01624357f01619f609a5b8a954'),
    'build-uart-shim-v2.py': (4875, '3c00f046cb51bf49e83dccb2fa741d6a9d38db163a236b71c4dc653dd226d3ea'),
    'sources/mkbootimg.py': (13371, '5579fb6bcb9e89e790a70fb9ccf3c00cf56e3e46aef74d84fcb0964887e5576e'),
    'build/libfdt-v2/libfdt-locked.so': (45696, '03c8661fb005cd967c768332622c6aed6415dbcdce31939de26933e61b388a18'),
}
FIXED = {
    'original_boot': ('outputs/rk3568-backup-linux-20261003/original/boot.img', SIZE,
                      '0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28'),
    'ramdisk': ('outputs/rk3568-pid1-20261005/build/production-v3/initramfs-pid1.cpio.gz', 972203,
                '54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef'),
    'rootfs': ('outputs/rk3568-pid1-20261005/build/production-v3/rootfs-pid1.ext4', 16777216,
               '3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d'),
    'prior_shim': (AUDIO + 'build/audio-ram-shim-v1/audio-ram-shim.dtb', 163204,
                   'c36b140c0ad18b79c3976f64239ef02251fc6986893afad7c474126725eb1e8b'),
    'original_dtbo': ('outputs/rk3568-backup-linux-20261003/original/dtbo.img', 4194304,
                      '59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d'),
}
RUNTIME_FIXED = {
    'audio-session-guard': (AUDIO + 'session-guard-v4/build/audio-session-guard', 741560,
                            '8740384398313be87a13245e854d6fc5a17a10f3794bdd83966e933c894c6f69'),
    'alsa-inspect': ('outputs/rk3568-audio-20261005/build/inspect-v4/alsa-inspect', 650408,
                     '118cf99482cdd65acdfae8c5e85530a76bf60c90b0b0498e8f285223f862a945'),
    'pcm-transfer': ('outputs/rk3568-audio-transfer-20261005/build/static-v1/pcm-transfer', 659736,
                     '2a6c765bd9c3c25b3456e60d68670231e81dcaf7781b827559cd701beed09e2e'),
    'pcm-peer-idle': (AUDIO + 'pcm-peer-idle-v1/production-v2/pcm-peer-idle', 655136,
                      '7693a052b6318ec3e965451fcb94609e97cb48e693715b847b62032cc684e661'),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def metadata(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'crc32': f'{zlib.crc32(data) & 0xffffffff:08x}'}


def relative(name):
    require(isinstance(name, str) and str(PurePosixPath(name)) == name and
            not name.startswith('/') and '\\' not in name and
            all(part not in ('', '.', '..') for part in name.split('/')), 'Canonical relative input required')
    path = ROOT / name
    require(path == path.resolve() and path.is_relative_to(ROOT), 'Symlink or escaped input')
    return path


def read(path, limit=64 * 1024 * 1024):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_relative_to(ROOT), 'Ordinary repository file required')
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit, 'Bounded ordinary file required')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(before.st_size + 1)
        after = os.fstat(descriptor)
        names = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        require(len(data) == before.st_size and all(getattr(before, n) == getattr(after, n) for n in names),
                'Input changed during read')
        return data
    finally:
        os.close(descriptor)


def checked_bytes(data, size, sha, label):
    require(type(size) is int and len(data) == size and isinstance(sha, str) and
            len(sha) == 64 and all(c in '0123456789abcdef' for c in sha) and
            metadata(data)['sha256'] == sha, 'Locked input changed: ' + label)
    return data


def locked(name, size, sha):
    return checked_bytes(read(relative(name)), size, sha, name)


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def unique_json(data):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'Duplicate JSON key')
            out[key] = value
        return out
    def invalid(value):
        raise ValueError('Non-finite JSON number: ' + value)
    value = json.loads(data.decode(), object_pairs_hook=pairs, parse_constant=invalid)
    require(isinstance(value, dict), 'JSON object required')
    return value


def module(name, blob):
    path = relative(PACKAGE + name)
    spec = importlib.util.spec_from_file_location('offline_' + name.replace('-', '_').replace('.', '_'), path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(blob, str(path), 'exec'), result.__dict__)
    return result


def dependencies():
    blobs = {PACKAGE + n: locked(PACKAGE + n, *identity) for n, identity in DEPENDENCIES.items()}
    modules = {n: module(n, blobs[PACKAGE + n]) for n in DEPENDENCIES if n.endswith('.py')}
    return modules, blobs


def check_profile(tree):
    props = tree['properties']
    def value(path, name):
        return props.get(path + ':' + name)
    expected = {
        CPU + ':compatible': b'rockchip,rk3568-i2s-tdm\0'.hex(),
        CPU + ':reg': struct.pack('>4I', 0, 0xfe410000, 0, 0x1000).hex(),
        CPU + ':status': b'okay\0'.hex(),
        CPU + ':rockchip,clk-trcm': '00000001',
        CPU + ':dmas': '000000b100000002000000b100000003',
        CPU + ':dma-names': b'tx\0rx\0'.hex(),
        CARD + ':compatible': b'simple-audio-card\0'.hex(),
        CARD + ':status': b'okay\0'.hex(),
        CARD + ':simple-audio-card,format': b'i2s\0'.hex(),
        CARD + ':simple-audio-card,mclk-fs': '00000100',
        CARD + '/simple-audio-card,cpu:sound-dai': '00000191',
        CARD + '/simple-audio-card,codec:sound-dai': '000002f9',
        CODEC + ':status': b'okay\0'.hex(),
        CODEC + ':assigned-clock-rates': '00bb8000',
    }
    require(all(props.get(key) == val for key, val in expected.items()), 'Actual fixed checked audio DT profile')
    require(value(CPU, 'rockchip,bclk-fs') in (None, '00000040'), 'BCLK ratio 64')
    forbidden = ('rockchip,always-on', 'rockchip,hdmi-path', 'rockchip,mclk-calibrate',
                 'rockchip,io-multiplex', 'rockchip,tdm-multi-lanes', 'rockchip,no-dmaengine',
                 'rockchip,digital-loopback', 'rockchip,i2s-tx-route', 'rockchip,i2s-rx-route',
                 'rockchip,playback-only', 'rockchip,capture-only')
    require(all(CPU + ':' + name not in props for name in forbidden), 'CPU checked profile exclusion')
    require(all('bitclock-master' not in key and 'frame-master' not in key
                for key in props if key.startswith(CARD + ':') or key.startswith(CARD + '/')), 'Default CPU master required')
    return {'actual_DT_profile_matched': True, 'CPU_checked_profile_selected_by_source': True,
            'CPU_master_from_simple_card_defaults': True, 'TRCM': 1, 'BCLK_fs': 64,
            'lrck_ratio_driver_default': 1, 'mclk_hz': 12288000, 'mclk_fs': 256,
            'runtime_rate_hz': 48000, 'runtime_channels': 2, 'runtime_format': 'S16_LE',
            'runtime_constraints_are_driver_contract_not_new_DT_properties': True,
            'MMIO_CCF_or_driver_execution': False}


def prepare_dt(data, overlay, modules):
    checked_bytes(data, FIXED['prior_shim'][1], FIXED['prior_shim'][2], 'prior_shim')
    checked_bytes(overlay, FIXED['original_dtbo'][1], FIXED['original_dtbo'][2], 'original_dtbo')
    semantic = modules['dt-semantics-v2.py']
    before = semantic.parse(data)
    profile = check_profile(before)
    handles = semantic.phandles(before)
    require(len(before['nodes']) == 962 and len(handles) == 762 and handles.get(0x191) == CPU and
            handles.get(0x2f9) == CODEC and handles.get(0x2fa) == '/chosen', 'Actual audio node/handle identities')
    require(all(path + ':' + FLAG not in before['properties'] for path in (CPU, CODEC)), 'Paired flag already present')
    real = modules['libfdt-v2.py'].RealLibFdt()
    opened = real.opened(data)
    for path in (CPU, CODEC):
        real.set_property(opened, path, FLAG, b'')
    candidate = real.packed(opened)
    after = semantic.parse(candidate)
    expected = {path + ':' + FLAG: {'before': None, 'after': ''} for path in (CPU, CODEC)}
    difference = semantic.diff(before, after)
    require(difference == expected and semantic.phandles(after) == handles, 'Exactly paired flags and unchanged metadata/handles')
    entry = modules['build-uart-shim-v2.py'].overlay_entry(overlay)
    apply_report, applied = real.apply(candidate, entry)
    require(apply_report['status'] == 0 and applied is not None, 'Actual libfdt original overlay apply')
    tree = semantic.parse(applied)
    reboot = [key.rsplit(':', 1)[0] for key in before['properties'] if key.endswith(':mode-normal')]
    require(len(reboot) == 1, 'Unique original reboot-mode identity')
    expected_overlay = {
        '/chosen:bootargs_ext': {'before': None, 'after': semantic.BOOT_DEVICES.hex()},
        reboot[0] + ':mode-bootloader': {'before': '5242c301', 'after': '5242c309'},
        reboot[0] + ':mode-fastboot': {'before': '5242c309', 'after': '5242c303'},
    }
    actual_overlay = semantic.diff(after, tree)
    require(actual_overlay == expected_overlay and semantic.phandles(tree) == handles and
            tree['properties'][reboot[0] + ':mode-normal'] == '5242c300', 'Only actual original overlay semantics')
    return candidate, applied, entry, {
        'mode': MODE, 'prior_shim': metadata(data), 'candidate': metadata(candidate),
        'complete_candidate_diff': difference, 'nodes': len(after['nodes']), 'phandles': len(handles),
        'nodes_reservations_boot_cpu_and_existing_phandles_unchanged': True,
        'profile': profile, 'real_libfdt': {'sha256': modules['libfdt-v2.py'].LIB_SHA,
            'apply': apply_report, 'applied_audit_only': metadata(applied), 'complete_overlay_diff': actual_overlay},
        'packaged_blob_is_pre_overlay': True, 'board_tested': False, 'START_authorized': False,
        'full_duplex_passed': False, 'flash_ready': False}


def fresh(name):
    path = HERE / name
    require(path == path.resolve() and path.is_relative_to(HERE) and path != HERE, 'Own fresh output required')
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_new(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def write_dt(name):
    modules, blobs = dependencies()
    base = locked(*FIXED['prior_shim'])
    dtbo = locked(*FIXED['original_dtbo'])
    candidate, applied, entry, receipt = prepare_dt(base, dtbo, modules)
    output = fresh(name)
    write_new(output / 'audio-shared-params-ram-shim.dtb', candidate)
    write_new(output / 'applied-audit-only.dtb', applied)
    write_new(output / 'overlay-entry0.dtbo', entry)
    receipt['tool'] = metadata(read(Path(__file__)))
    receipt['dependency_identities'] = {n: metadata(b) for n, b in blobs.items()}
    write_new(output / 'receipt.json', json_bytes(receipt))
    print(json.dumps({'output': str(output.relative_to(ROOT)), 'candidate': receipt['candidate'],
                      'real_overlay_status': 0, 'board_tested': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    dt = commands.add_parser('dt')
    dt.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'dt':
            write_dt(args.out)
    except (ValueError, OSError) as error:
        parser.exit(1, 'OFFLINE_CANDIDATE_REJECTED: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
