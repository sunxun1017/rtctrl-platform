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
RELEASE = '5.10.160-rt89-g9f9e9d18574d-dirty'
INTEGRATION = AUDIO + 'build/root-audio-integration-v5/'
NEW = {
    'Image': ('.deps/kernel/aiot-3568pq-audio-v5/arch/arm64/boot/Image', 34755072,
              'e2a5590fbde0a431a1a900c5fc9789d1e607af71a5300010e5431a2927ae3f61'),
    'codec': (INTEGRATION + 'canonical-codec-v1/modules/snd-soc-rk817.ko', 606536,
              'c43e470ccf7219bd344ba9d7315b38599f6b0eafb8a2ea6700eee34de9e13d85'),
    'kernel.notes': (INTEGRATION + 'canonical-codec-v1/kernel.notes', 60,
                     'cb073cb3bccb0e2be9054cb84a4415681a6abb2e17b90a169f25a24561652e33'),
    'build_receipt': (INTEGRATION + 'full-build-v1/receipt.json', 3017,
                      '054a132eb340b07d147024223bf9fe7ccd239526b10ee23e586ae8c350b5ec5b'),
    'codec_receipt': (INTEGRATION + 'canonical-codec-v1/receipt.json', 18867,
                      'ecca10f61c6c35af462a1c483f42a495062d98780f8ebc41caa73f541787bfa7'),
    'dt': (AUDIO + 'offline-next-delivery-v1/dt-v1/audio-shared-params-ram-shim.dtb', 163263,
           '85f09184db921d6cf4fe7fac9f209bcd69236085af391a263c830a87ce70449a'),
    'dt_receipt': (AUDIO + 'offline-next-delivery-v1/dt-v1/receipt.json', 4380,
                   '85468ceeae2b8af76cff93bd5ff3c8af10592a25b037c76281bd7ae7ffb3077c'),
}
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


def validate_new_records(build, codec, image, module_data, notes, build_sha):
    """Bind exact new actual products; producer source review is a separate root result."""
    checked_bytes(image, NEW['Image'][1], NEW['Image'][2], 'new Image')
    checked_bytes(module_data, NEW['codec'][1], NEW['codec'][2], 'canonical codec')
    checked_bytes(notes, NEW['kernel.notes'][1], NEW['kernel.notes'][2], 'actual kernel notes')
    require(build.get('Image_and_modules_built') is True and build.get('codec_module_built') is True and
            build.get('source_after_matches_before') is True and build.get('source_files') == 89423 and
            build.get('config_sha256') == '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912' and
            build.get('kernel_release') == RELEASE and isinstance(build.get('steps'), list) and
            len(build['steps']) == 2 and all(type(s.get('exit')) is int and s['exit'] == 0 for s in build['steps']),
            'Actual complete Image build receipt')
    expected_image = dict(path=NEW['Image'][0], bytes=len(image), sha256=metadata(image)['sha256'])
    require(build.get('actual_products', {}).get('Image') == expected_image and codec.get('Image') == expected_image,
            'Actual Image byte/path binding in both receipts')
    require(codec.get('Image_receipt_sha256') == build_sha == NEW['build_receipt'][2] and
            codec.get('kernel_release') == RELEASE and codec.get('generated_inputs_unchanged') is True and
            codec.get('generated_records') == 2020 and codec.get('module_filename') == 'snd-soc-rk817.ko' and
            codec.get('module_internal_name') == 'snd_soc_rk817' and isinstance(codec.get('steps'), list) and
            len(codec['steps']) == 5 and all(type(s.get('exit')) is int and s['exit'] == 0 for s in codec['steps']),
            'Canonical actual module build/generated ABI receipt')
    info = codec.get('module', {})
    vermagic = RELEASE + ' SMP preempt_rt mod_unload aarch64'
    require(info.get('bytes') == len(module_data) and info.get('sha256') == metadata(module_data)['sha256'] and
            info.get('metadata', {}).get('name') == ['snd_soc_rk817'] and
            info.get('metadata', {}).get('vermagic') == [vermagic] and
            info.get('imports_resolved') is True and info.get('imports_from_actual_Module_and_vmlinux_symvers') is True and
            isinstance(info.get('imports'), dict) and len(info['imports']) == 37 and
            all(info.get(k) is False for k in ('elf_has_interp', 'elf_has_needed', 'MODVERSIONS_enabled',
                '__versions_section_present', 'CRC_runtime_enforcement_claimed', 'unload_safe', 'board_tested')),
            'Actual audited canonical module byte/import/boundary binding')
    require(module_data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<HH', module_data, 16) == (1, 183) and
            b'name=snd_soc_rk817\0' in module_data and b'vermagic=' + vermagic.encode() + b'\0' in module_data,
            'Actual module AArch64 ET_REL/name/vermagic bytes')
    require(codec.get('kernel_notes') == {'bytes': len(notes), 'sha256': metadata(notes)['sha256']} and
            all(codec.get(k) is False for k in ('board_tested', 'loaded', 'unload_tested', 'full_migration_completed')),
            'Actual new kernel notes and no board acceptance')
    return {'actual_completed_Image_and_modules': True, 'canonical_codec_imports': 37,
            'generated_ABI_records_bound_by_producer': 2020, 'producer_receipts_verified': True,
            'producer_global_source_inventory_reexecution_in_this_tool': False,
            'producer_full_generated_ABI_reexecution_in_this_tool': False,
            'source_independent_review_is_root_responsibility': True,
            'board_tested': False, 'START_authorized': False, 'full_duplex_passed': False}


def overlaps(spans):
    return [{'left': name, 'right': other, 'intersection': [max(start, left), min(end, right)]}
            for index, (name, start, end) in enumerate(spans)
            for other, left, right in spans[index + 1:] if max(start, left) < min(end, right)]


def address_plan(image, header, sizes, applied_size):
    require(len(image) >= 64 and image[56:60] == b'ARM\x64' and image[32:56] == bytes(24), 'ARM64 Image header')
    offset, memory, flags = struct.unpack_from('<QQQ', image, 8)
    require(len(image) <= memory <= 0xffffffffffffffff - 0x400000 and offset <= 0x400000 and
            (0x400000 - offset) % 0x200000 == 0 and flags & 1 == 0 and flags >> 4 == 0 and
            (flags >> 1) & 3 == 1 and flags & 8 != 0, 'ARM64 effective extent/placement/4K/LE flags')
    require(set(sizes) == {'kernel', 'ramdisk', 'second', 'dtb'} and
            all(type(n) is int and n > 0 for n in sizes.values()), 'Positive exact component sizes')
    require(max(sizes['dtb'], applied_size) <= 0x40000, 'FDT workspace capacity')
    spans = [('kernel', 0x400000, 0x400000 + memory), ('fdt_workspace', 0xa100000, 0xa140000),
             ('initrd', 0x4000000, 0x4000000 + sizes['ramdisk']), ('package', 0x20000000, 0x22800000)]
    require(not overlaps(spans), 'Temporary RAM destination intervals overlap')
    banks = [[0x200000, 0x8400000], [0x9400000, 0xf0000000]]
    require(all(any(left <= start < end <= right for left, right in banks) for _, start, end in spans),
            'Temporary RAM span outside historical bank constraints')
    encoded = [(n, header[n + '_addr'], header[n + '_addr'] + (memory if n == 'kernel' else sizes[n]))
               for n in ('kernel', 'ramdisk', 'second', 'dtb')]
    return {'image_header': {'text_offset': offset, 'image_size': memory, 'flags': flags},
            'temporary_destinations': {n: [s, e] for n, s, e in spans}, 'temporary_overlaps': [],
            'encoded_header_spans': {n: [s, e] for n, s, e in encoded}, 'encoded_header_overlaps': overlaps(encoded),
            'encoded_header_addresses_are_actual_destinations': False, 'historical_banks': banks,
            'fresh_bank_reserved_relocation_and_destination_check_completed': False,
            'old_memreserve_metadata_preserved': True, 'actual_board_destinations_verified': False}


def inspect_padded(data, payloads, original, modules, dt_report):
    require(len(data) == SIZE, 'Complete 40 MiB candidate required')
    report = modules['audit-boot.py'].inspect_boot(data, expected_concat_count=1)
    header = report['header']
    for name in ('version', 'header_size', 'page_size', 'kernel_addr', 'ramdisk_addr', 'second_addr',
                 'tags_addr', 'dtb_addr', 'os_version_encoded', 'board'):
        require(header[name] == original['header'][name], 'Original v2 header policy: ' + name)
    require(header['cmdline'] == CMDLINE, 'Exact bounded Linux command line')
    for component in report['components']:
        blob = payloads[component['name']]
        require(all(component[k] == v for k, v in metadata(blob).items()) and
                data[component['offset']:component['offset'] + component['bytes']] == blob,
                'Exact selected component content: ' + component['name'])
    current, prior = report['resource']['entries'], original['resource']['entries']
    require([e['path'] for e in current] == [e['path'] for e in prior], 'Original 11 RSCE names/order')
    extent = 12 * 512
    for entry, old in zip(current, prior):
        require(entry['offset'] == extent, 'Canonical RSCE extent')
        extent += (entry['bytes'] + 511) & ~511
        expected = metadata(payloads['dtb']) if entry['path'].endswith('.dtb') else old
        require(all(entry[k] == expected[k] for k in ('bytes', 'sha256', 'crc32')), 'Nine paired DTs and two identical original logos')
    require(extent == len(payloads['second']), 'Exact RSCE whole extent')
    projected = header['page_size'] + sum((len(b) + header['page_size'] - 1) & ~(header['page_size'] - 1)
                                        for b in payloads.values())
    require(report['raw_bytes'] == projected <= SIZE and not any(data[projected:]), 'Raw extent and all zero partition padding')
    plan = address_plan(payloads['kernel'], header, {n: len(b) for n, b in payloads.items()},
                        dt_report['real_libfdt']['applied_audit_only']['bytes'])
    report.update({'mode': MODE, 'address_analysis': plan, 'real_overlay': dt_report['real_libfdt'],
                   'complete_new_DT_difference': dt_report['complete_candidate_diff'],
                   'packaged_DT_is_pre_overlay': True, 'zero_padding_verified': True,
                   'board_tested': False, 'START_authorized': False, 'flash_ready': False,
                   'full_migration_completed': False})
    return report


def build_package(name):
    modules, deps = dependencies()
    fixed = {n: locked(*identity) for n, identity in FIXED.items()}
    new = {n: locked(*identity) for n, identity in NEW.items()}
    build = unique_json(new['build_receipt'])
    codec = unique_json(new['codec_receipt'])
    bindings = validate_new_records(build, codec, new['Image'], new['codec'], new['kernel.notes'],
                                    metadata(new['build_receipt'])['sha256'])
    dt, applied, entry, dt_report = prepare_dt(fixed['prior_shim'], fixed['original_dtbo'], modules)
    require(dt == new['dt'] and unique_json(new['dt_receipt'])['candidate'] == metadata(dt), 'Exact prepared new DT identity')
    # Only finite current source and symvers/config files are reread. The complete
    # source/ABI inventory remains the explicitly bound producer's evidence.
    finite = {}
    for label, path, sha in [
        ('config', '.deps/kernel/aiot-3568pq-audio-v5/.config', build['config_sha256']),
        ('Module.symvers', build['actual_products']['Module.symvers']['path'], build['actual_products']['Module.symvers']['sha256']),
        ('codec source', '.deps/kernel-source/aiot-3568pq-audio-v5/sound/soc/codecs/rk817_codec.c', codec['source_sha256']),
        ('soc-dai header', '.deps/kernel-source/aiot-3568pq-audio-v5/include/sound/soc-dai.h', codec['soc_dai_header_sha256']),
        ('soc header', '.deps/kernel-source/aiot-3568pq-audio-v5/include/sound/soc.h', codec['soc_header_sha256'])]:
        blob = read(relative(path))
        require(metadata(blob)['sha256'] == sha, 'Finite actual source/ABI drift: ' + label)
        finite[path] = blob
    runtime = {n: locked(*identity) for n, identity in RUNTIME_FIXED.items()}
    runtime['snd-soc-rk817.ko'] = new['codec']
    original = modules['audit-boot.py'].inspect_boot(fixed['original_boot'])
    payloads = {'kernel': new['Image'], 'ramdisk': fixed['ramdisk'], 'dtb': dt}
    payloads['second'] = modules['build-ram-candidate-v2.py'].build_resource(fixed['original_boot'], original, dt)
    header = original['header']
    require(header['version'] == 2 and header['page_size'] == 2048, 'Original v2 page contract')
    address_plan(payloads['kernel'], header, {n: len(b) for n, b in payloads.items()}, len(applied))
    projected = 2048 + sum((len(b) + 2047) & ~2047 for b in payloads.values())
    require(projected <= SIZE, 'New candidate exceeds 40 MiB')
    output = fresh(name)
    components = output / 'components'
    components.mkdir()
    for n, blob in payloads.items():
        write_new(components / n, blob)
    official = modules['build-roundtrip.py'].official_module(relative(PACKAGE + 'sources/mkbootimg.py'))
    with ExitStack() as stack:
        stream = stack.enter_context((output / 'boot-raw.img').open('xb'))
        files = {n: stack.enter_context((components / n).open('rb')) for n in payloads}
        args = SimpleNamespace(output=stream, **files, recovery_dtbo=None, header_version=2, pagesize=2048,
            base=0, kernel_offset=header['kernel_addr'], ramdisk_offset=header['ramdisk_addr'],
            second_offset=header['second_addr'], tags_offset=header['tags_addr'], dtb_offset=header['dtb_addr'],
            os_version=header['os_version'], os_patch_level=header['os_patch_level'], board=header['board'], cmdline=CMDLINE)
        official.write_header(args)
        official.write_data(args, 2048)
        stream.flush()
        os.fsync(stream.fileno())
    raw = read(output / 'boot-raw.img')
    require(len(raw) == projected, 'Actual official writer extent')
    padded = raw + bytes(SIZE - len(raw))
    audit = inspect_padded(padded, payloads, original, modules, dt_report)
    write_new(output / 'boot-padded.img', padded)
    write_new(output / 'audit.json', json_bytes(audit))
    sidecars = output / 'runtime'
    sidecars.mkdir()
    for n, blob in runtime.items():
        write_new(sidecars / n, blob)
    sums = ''.join(metadata(blob)['sha256'] + '  ' + n + '\n' for n, blob in sorted(runtime.items())).encode()
    write_new(sidecars / 'SHA256SUMS', sums)
    write_new(output / 'rootfs-pid1.ext4', fixed['rootfs'])
    write_new(output / 'kernel.notes', new['kernel.notes'])
    write_new(output / 'applied-audit-only.dtb', applied)
    write_new(output / 'overlay-entry0.dtbo', entry)
    inputs = output / 'source-inputs'
    inputs.mkdir()
    snapshot = dict(deps)
    snapshot.update({identity[0]: new[n] for n, identity in NEW.items() if n.endswith('receipt')})
    snapshot.update(finite)
    snapshot[str(Path(__file__).relative_to(ROOT))] = read(Path(__file__))
    snapshot[str((HERE / 'offline-next-dt-v1.py').relative_to(ROOT))] = read(HERE / 'offline-next-dt-v1.py')
    for n, blob in snapshot.items():
        path = inputs / n
        path.parent.mkdir(parents=True, exist_ok=True)
        write_new(path, blob)
    # Actual second read makes input drift a refusal, not a new identity accepted
    # from late mutable paths. All output files retain the first selected bytes.
    for table in (DEPENDENCIES,):
        for n, identity in table.items():
            require(locked(PACKAGE + n, *identity) == deps[PACKAGE + n], 'Dependency changed before completion')
    for table, blobs in ((FIXED, fixed), (NEW, new), (RUNTIME_FIXED, runtime)):
        for n, identity in table.items():
            require(locked(*identity) == blobs[n], 'Input changed before completion: ' + n)
    for n, blob in finite.items():
        require(read(relative(n)) == blob, 'Finite actual source/ABI changed before completion')
    require(read(Path(__file__)) == snapshot[str(Path(__file__).relative_to(ROOT))], 'Own builder changed before completion')
    manifest = {'schema': 1, 'mode': MODE, 'offline_format_constructed': True,
        'producer_binding': bindings, 'inputs': {n: {'path': identity[0], **metadata(new[n])} for n, identity in NEW.items()},
        'fixed_inputs': {n: {'path': identity[0], **metadata(fixed[n])} for n, identity in FIXED.items()},
        'runtime': {n: metadata(blob) for n, blob in runtime.items()}, 'components': {n: metadata(blob) for n, blob in payloads.items()},
        'artifacts': {'boot-raw.img': metadata(raw), 'boot-padded.img': metadata(padded)},
        'kernel_release': RELEASE, 'official_mkbootimg_commit': '99894068024224a62595e051d69e748e2499f52e',
        'official_mkbootimg_functions': ['write_header', 'write_data'], 'source_input_metadata': {n: metadata(b) for n, b in snapshot.items()},
        'complete_DT': dt_report, 'address_analysis': audit['address_analysis'],
        'rootfs_board_path': '/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4',
        'native_pid1_old_rcu_image_check_is_new_image_identity': False,
        'rootfs_and_initramfs_are_identical_prior_accepted_bytes': True,
        'old_v5_production_acceptance_gate_used': False, 'root_independent_review_completed_by_this_tool': False,
        'early_uboot_DT': 'ORIGINAL_EMMC_RESOURCE_UNCHANGED_RAM_ONLY',
        'required_before_any_board_execution': ['root final independent source/ABI/package acceptance',
            'fresh RAM banks and reserved/relocation ranges', 'fresh environment and actual destinations',
            'full padded transferred SHA/CRC', 'root controlled one-argument RAM boot'],
        'required_hardware_acceptance': ['new live Image/kernel.notes and full DT/overlay identities',
            'new paired parameter ownership and actual duplex transfer/IRQ/FIFO behavior',
            'module/card/CPU/PL330 close and normal shutdown', 'physical input/output with reconnected peripherals',
            'return to Android and protected partition equality'],
        'board_tested': False, 'START_authorized': False, 'loaded': False, 'deployed': False,
        'full_duplex_passed': False, 'physical_audio_verified': False, 'flash_ready': False,
        'formal_flash_ready': False, 'saveenv': False, 'TUN_modified': False, 'full_migration_completed': False}
    write_new(output / 'manifest.json', json_bytes(manifest))
    inventory = {p.relative_to(output).as_posix(): metadata(read(p)) for p in sorted(output.rglob('*')) if p.is_file()}
    receipt = {'schema': 1, 'mode': MODE, 'files_before_receipt': inventory,
               'complete_file_count_excluding_receipt': len(inventory), 'all_selected_inputs_unchanged': True,
               'board_tested': False, 'START_authorized': False, 'formal_flash_ready': False}
    write_new(output / 'receipt.json', json_bytes(receipt))
    print(json.dumps({'output': str(output.relative_to(ROOT)), 'raw': metadata(raw), 'padded': metadata(padded),
        'runtime_files': len(runtime), 'complete_files_excluding_receipt': len(inventory), 'board_tested': False,
        'START_authorized': False, 'formal_flash_ready': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    dt = commands.add_parser('dt')
    dt.add_argument('--out', required=True)
    package = commands.add_parser('package')
    package.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'dt':
            write_dt(args.out)
        elif args.command == 'package':
            build_package(args.out)
    except (ValueError, OSError) as error:
        parser.exit(1, 'OFFLINE_CANDIDATE_REJECTED: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
