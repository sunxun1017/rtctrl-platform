#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""SHA-bound offline audio RAM package policy. No device or flashing operations."""
from contextlib import ExitStack
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
from types import ModuleType, SimpleNamespace
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = 'outputs/rk3568-boot-package-20261005/'
RUNTIME = 'outputs/rk3568-audio-runtime-20261005/'
PRODUCTION = RUNTIME + 'build/integration-v1/'
CMDLINE = 'console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init ro loglevel=7 panic=0'
SIZE = 40 * 1024 * 1024
COMMIT = '9f9e9d18574d0914c0d192a90c3babfe1fd63c95'
CONFIG = '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'
CPU_MANIFEST = '92344de6c38aeb3353134150ec9bca75fad84dc3d2071e1bbd7d611fd0d73b56'
OFFICIAL_COMMIT = '99894068024224a62595e051d69e748e2499f52e'
LOCKS = {
    'third_party/linux-rk3588/Documentation/arm64/booting.rst': (12197, 'ed228088e1908ff94c1236f63efb46b4975b7dcd7bfede2cd059d83ea9d330d0'),
    PACKAGE + 'audit-boot.py': (15327, '4902a1281665d58f7e053838af5547522cc6f227c2be1baf6d260cf2ccd6067d'),
    PACKAGE + 'build-roundtrip.py': (8679, 'b485eaf390799c9af2de2b25e5a79c77db3b368de0e5784c6b08c620492b18fc'),
    PACKAGE + 'build-ram-candidate-v2.py': (11504, '298c0c6620ad0703d5566b233176cd276b0404e589d94152c9ae809ddb7eae1d'),
    PACKAGE + 'dt-semantics-v2.py': (5164, 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56'),
    PACKAGE + 'libfdt-v2.py': (5537, '9fdba61ae8d7d004ac7f24b7f116f6a314032c01624357f01619f609a5b8a954'),
    PACKAGE + 'build-uart-shim-v2.py': (4875, '3c00f046cb51bf49e83dccb2fa741d6a9d38db163a236b71c4dc653dd226d3ea'),
    PACKAGE + 'sources/mkbootimg.py': (13371, '5579fb6bcb9e89e790a70fb9ccf3c00cf56e3e46aef74d84fcb0964887e5576e'),
    PACKAGE + 'build/libfdt-v2/libfdt-locked.so': (45696, '03c8661fb005cd967c768332622c6aed6415dbcdce31939de26933e61b388a18'),
    PACKAGE + 'build/libfdt-v2/manifest.json': (4131, '9404a7d2e7e1070197e06f265b46db753e71586765e2a68f335ad8b6128bbe96'),
    RUNTIME + 'build-audio-ram-shim.py': (5573, '5aeb0f5f9cc7092cedc7f1975d9097a2e95f5bfa1e8b58fb27be09b64564b749'),
    RUNTIME + 'build/audio-ram-shim-v1/manifest.json': (3591, '9557c06318faa92380e736464032eaede8589f5af4335bab2c61282925fdd381'),
}
FIXED = {
    'original': ('outputs/rk3568-backup-linux-20261003/original/boot.img', SIZE,
                 '0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28'),
    'ramdisk': ('outputs/rk3568-pid1-20261005/build/production-v3/initramfs-pid1.cpio.gz', 972203,
                '54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef'),
    'rootfs': ('outputs/rk3568-pid1-20261005/build/production-v3/rootfs-pid1.ext4', 16777216,
               '3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d'),
    'dtb': (RUNTIME + 'build/audio-ram-shim-v1/audio-ram-shim.dtb', 163204,
            'c36b140c0ad18b79c3976f64239ef02251fc6986893afad7c474126725eb1e8b'),
    'audio_baseline': ('outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb', 163161,
                       '9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478'),
    'dtbo': ('outputs/rk3568-backup-linux-20261003/original/dtbo.img', 4194304,
             '59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d'),
}
APPLIED = (163285, '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f')


def require(value, message):
    if not value:
        raise ValueError(message)


def metadata(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'crc32': f'{zlib.crc32(data) & 0xffffffff:08x}'}


def relative_path(name):
    require(isinstance(name, str) and str(PurePosixPath(name)) == name and
            not name.startswith('/') and '\\' not in name and
            all(part not in ('', '.', '..') for part in name.split('/')), 'Repository relative path required')
    path = ROOT / name
    require(path == path.resolve() and path.is_relative_to(ROOT), 'Symlink/escaped input rejected: ' + name)
    return path


def read_ordinary(path, limit=64 * 1024 * 1024):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_relative_to(ROOT), 'Ordinary repository file required')
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit, 'Bounded ordinary file required')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(before.st_size + 1)
        after = os.fstat(descriptor)
        require(len(data) == before.st_size and
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                'Input changed during read')
        return data
    finally:
        os.close(descriptor)


def read_locked(name, size, sha):
    data = read_ordinary(relative_path(name))
    require(len(data) == size and metadata(data)['sha256'] == sha, 'Locked input changed: ' + name)
    return data


def unique_json(data):
    def pairs(items):
        result = {}
        for name, value in items:
            require(name not in result, 'Duplicate JSON key')
            result[name] = value
        return result
    def bad_constant(value):
        raise ValueError('Non-finite JSON number: ' + value)
    result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=bad_constant)
    require(isinstance(result, dict), 'JSON object required')
    return result


def digest(value):
    require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'Full lowercase SHA256 required')
    return value


def verify_hash_map(mapping):
    require(isinstance(mapping, dict) and bool(mapping), 'Nonempty source hash map required')
    for name, sha in mapping.items():
        data = read_ordinary(relative_path(name))
        require(metadata(data)['sha256'] == digest(sha), 'Reviewed file changed: ' + name)


@lru_cache(maxsize=1)
def dependencies():
    checked = {name: read_locked(name, size, sha) for name, (size, sha) in LOCKS.items()}
    lib_manifest = unique_json(checked[PACKAGE + 'build/libfdt-v2/manifest.json'])
    require(len(lib_manifest['sources']) == 13, 'Locked libfdt source count')
    for name, info in lib_manifest['sources'].items():
        path = PACKAGE + 'build/libfdt-v2/libfdt-source/' + name
        checked[path] = read_locked(path, info['bytes'], info['sha256'])
    modules = {}
    for name in ('audit-boot.py', 'build-roundtrip.py', 'build-ram-candidate-v2.py',
                 'dt-semantics-v2.py', 'libfdt-v2.py', 'build-uart-shim-v2.py'):
        path = relative_path(PACKAGE + name)
        module = ModuleType('audio_locked_' + name.replace('-', '_').replace('.', '_'))
        module.__file__ = str(path)
        exec(compile(checked[PACKAGE + name], str(path), 'exec'), module.__dict__)
        modules[name] = module
    return modules, checked


def overlaps(spans):
    result = []
    for index, (name, start, end) in enumerate(spans):
        for other, left, right in spans[index + 1:]:
            if max(start, left) < min(end, right):
                result.append({'left': name, 'right': other,
                               'intersection': [max(start, left), min(end, right)]})
    return result


def image_plan(image, header, component_sizes):
    require(len(image) >= 64 and image[56:60] == b'ARM\x64', 'ARM64 Image magic/header')
    require(set(component_sizes) == {'kernel', 'ramdisk', 'second', 'dtb'} and
            all(type(size) is int and size > 0 for size in component_sizes.values()),
            'Positive integer component sizes required')
    text_offset, image_size, flags = struct.unpack_from('<QQQ', image, 8)
    require(len(image) <= image_size <= 0xffffffffffffffff - 0x400000, 'ARM64 bounded effective memory size')
    require(flags & 1 == 0 and flags >> 4 == 0 and (flags >> 1) & 3 == 1,
            'ARM64 little-endian 4 KiB config/defined flag bits required')
    require(flags & 8 != 0, '4 MiB plan requires any-physical-base placement flag')
    require(text_offset <= 0x400000 and (0x400000 - text_offset) % 0x200000 == 0,
            'ARM64 text_offset/2 MiB base alignment')
    require(image[32:56] == bytes(24), 'ARM64 reserved header fields')
    spans = [('kernel', 0x400000, 0x400000 + image_size),
             ('fdt_workspace', 0xa100000, 0xa140000),
             ('initrd', 0x4000000, 0x4000000 + component_sizes['ramdisk']),
             ('package', 0x20000000, 0x22800000)]
    require(component_sizes['dtb'] <= 0x40000 and APPLIED[0] <= 0x40000,
            'FDT blob exceeds conservative workspace')
    require(component_sizes['ramdisk'] > 0, 'Empty initrd')
    require(not overlaps(spans), 'Candidate actual plan intervals overlap')
    # These are static constraints from the earlier trial, not a fresh bdinfo result.
    historical_banks = [[0x200000, 0x8400000], [0x9400000, 0xf0000000]]
    require(any(left <= 0x400000 - text_offset < right for left, right in historical_banks),
            'ARM64 aligned base outside historical usable bank')
    require(all(any(left <= start < end <= right for left, right in historical_banks)
                for _, start, end in spans), 'Candidate span outside historical bank constraints')
    header_spans = [(name, header[name + '_addr'], header[name + '_addr'] +
                     (image_size if name == 'kernel' else component_sizes[name]))
                    for name in ('kernel', 'ramdisk', 'second', 'dtb')]
    return {'image_header': {'text_offset': text_offset, 'image_size': image_size, 'flags': flags},
            'actual_plan': {name: [start, end] for name, start, end in spans},
            'actual_plan_overlaps': [], 'kernel_2m_aligned_base': 0x400000 - text_offset,
            'header_destination_intervals': {name: [start, end] for name, start, end in header_spans},
            'header_destination_overlaps': overlaps(header_spans),
            'header_addresses_are_actual_destinations': False,
            'old_fdt_memreserve': {'interval': [0xa100000, 0xa125000],
                'classification': 'SAME_PURPOSE_FDT_RESERVATION_INSIDE_GD_WORKSPACE'},
            'old_initrd_memreserve': {'interval': [0xa200000, 0xa2c8c20],
                'classification': 'UNCHANGED_OLD_ADDRESS_METADATA_NOT_CURRENT_INITRD'},
            'historical_bank_constraints': historical_banks,
            'fresh_bank_and_reserved_ranges_verified': False,
            'actual_destinations_verified': False,
            'gd_fdt_addr_must_equal_temporary_fdt_addr_r': 0xa100000,
            'fresh_gd_env_relocation_reserved_and_full_crc_required': True}


def validate_image_metadata(manifest, image):
    """Pure complete Image/header binding, also exercised without unavailable build artifacts."""
    info = metadata(image)
    require(type(manifest.get('image_bytes')) is int and manifest['image_bytes'] == info['bytes'] and
            digest(manifest['image_sha256']) == info['sha256'] and manifest.get('image_crc32') == info['crc32'],
            'Complete Image content binding')
    require(len(image) >= 64 and image[56:60] == b'ARM\x64', 'Manifest Image magic')
    require(type(manifest.get('text_offset')) is int and
            manifest['text_offset'] == struct.unpack_from('<Q', image, 8)[0] and
            type(manifest.get('image_memory_bytes')) is int and
            manifest['image_memory_bytes'] == struct.unpack_from('<Q', image, 16)[0], 'Manifest Image header binding')
    require(manifest.get('kernel_release') == '5.10.160-rt89-g9f9e9d18574d-dirty', 'Expected kernel release')
    return info


def validate_review(manifest, gate, gate_data, image):
    """Validate provenance fields against actual files before using manifest Image hashes."""
    require(gate.get('accepted_for_offline_integration') is True, 'Independent C3 integration gate required')
    bound = gate.get('files_sha256')
    verify_hash_map(bound)
    require(manifest.get('reviewed_files_sha256') == bound and
            manifest.get('review_gate_sha256') == metadata(gate_data)['sha256'], 'Image review gate binding')
    require(manifest.get('source_commit') == COMMIT and manifest.get('config_sha256') == CONFIG and
            manifest.get('cpu_manifest_sha256') == CPU_MANIFEST, 'Image source/config/CPU binding')
    require(type(manifest.get('build_exit_code')) is int and manifest['build_exit_code'] == 0 and
            manifest.get('original_clean') is True and manifest.get('deployed') is False and
            manifest.get('board_tested') is False, 'Successful offline Image build required')
    c3_name = gate.get('c3_manifest')
    require(c3_name in bound and manifest.get('c3_manifest_sha256') == bound[c3_name], 'Image C3 manifest binding')
    c3 = unique_json(read_ordinary(relative_path(c3_name)))
    require(c3.get('kernel_commit') == COMMIT, 'C3 source commit')
    c3_dir = str(PurePosixPath(c3_name).parent)
    c3_patch = c3_dir + '/C3-lifecycle-review.patch'
    c3_patch_data = read_ordinary(relative_path(c3_patch))
    require(metadata(c3_patch_data)['sha256'] == digest(c3['patch_sha256']), 'C3 patch binding')
    sources = {c3_dir + '/' + name: sha for name, sha in c3['source_sha256'].items()}
    verify_hash_map(sources)
    patches = manifest.get('patches_sha256')
    verify_hash_map(patches)
    expected_public = set()
    for number in range(1, 11):
        matches = sorted((ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches').glob(f'{number:04d}-*.patch'))
        require(len(matches) == 1, 'Unique public patch required')
        name = str(matches[0].relative_to(ROOT))
        require(patches.get(name) == bound.get(name) == metadata(read_ordinary(matches[0]))['sha256'],
                'Image public patch gate binding')
        expected_public.add(name)
    cpu_patch = 'outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10/i2s-lifecycle-pm.patch'
    require(set(patches) == expected_public | {c3_patch, cpu_patch}, 'Image exact patch series')
    require(patches[c3_patch] == c3['patch_sha256'] and patches[cpu_patch] ==
            'ec857605a70abccce88ac71c1e5070b866fb245717ad90ae0db2af26fc9aa495', 'Image C3/CPU patch identity')
    require(metadata(read_ordinary(relative_path(RUNTIME + 'build-audio-image.py')))['sha256'] ==
            digest(manifest['builder_sha256']), 'Image builder binding')
    require(manifest.get('compiler') == 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0',
            'Image compiler binding')
    validate_image_metadata(manifest, image)
    require(metadata(read_ordinary(relative_path(PRODUCTION + 'kernel.config')))['sha256'] == CONFIG,
            'Actual Image config file')
    for name, key in [('Module.symvers', 'module_symvers_sha256'), ('vmlinux.symvers', 'vmlinux_symvers_sha256')]:
        require(metadata(read_ordinary(relative_path(PRODUCTION + name)))['sha256'] == digest(manifest[key]),
                'Exact Image symbol table binding: ' + name)
    return {'review_gate': metadata(gate_data), 'c3_manifest': {'path': c3_name, 'sha256': bound[c3_name]},
            'reviewed_files_sha256': bound, 'patches_sha256': patches,
            'builder_sha256': manifest['builder_sha256'], 'source_sha256': sources}


def production_inputs(review_gate):
    dependencies()
    manifest_data = read_ordinary(relative_path(PRODUCTION + 'manifest.json'), 4 * 1024 * 1024)
    gate_data = read_ordinary(relative_path(review_gate), 4 * 1024 * 1024)
    manifest, gate = unique_json(manifest_data), unique_json(gate_data)
    image = read_ordinary(relative_path(PRODUCTION + 'Image'))
    provenance = validate_review(manifest, gate, gate_data, image)
    return {'kernel': image, 'mode': 'RAM_ONLY_NOT_FLASH_READY',
            'image_manifest': {'path': PRODUCTION + 'manifest.json', **metadata(manifest_data)},
            'review_gate': {'path': review_gate, **metadata(gate_data)}, 'provenance': provenance}


def fixed_inputs():
    return {name: read_locked(*fields) for name, fields in FIXED.items()}


def inspect_candidate(data, image_inputs):
    modules, checked = dependencies()
    require(len(data) == SIZE, 'Candidate complete 40 MiB required')
    require(image_inputs['mode'] in ('RAM_ONLY_NOT_FLASH_READY', 'FIXTURE_ONLY_NOT_DEPLOYABLE'),
            'Explicit production or fixture mode required')
    audit = modules['audit-boot.py']
    report = audit.inspect_boot(data, expected_concat_count=1)
    fixed = fixed_inputs()
    original = audit.inspect_boot(fixed['original'])
    expected = {'kernel': metadata(image_inputs['kernel']), 'ramdisk': metadata(fixed['ramdisk']),
                'dtb': metadata(fixed['dtb'])}
    for component in report['components']:
        if component['name'] in expected:
            require(all(component[key] == value for key, value in expected[component['name']].items()),
                    'Locked component policy: ' + component['name'])
    header = report['header']
    for name in ('version', 'header_size', 'page_size', 'kernel_addr', 'ramdisk_addr', 'second_addr',
                 'tags_addr', 'dtb_addr', 'os_version_encoded', 'board'):
        require(header[name] == original['header'][name], 'Original header metadata policy: ' + name)
    require(header['cmdline'] == CMDLINE, 'Fixed Linux cmdline policy')
    entries, old = report['resource']['entries'], original['resource']['entries']
    require([entry['path'] for entry in entries] == [entry['path'] for entry in old], 'Original RSCE names/order policy')
    end = 12 * 512
    for entry, prior in zip(entries, old):
        require(entry['offset'] == end, 'Canonical RSCE offset policy')
        end += (entry['bytes'] + 511) & ~511
        selected = expected['dtb'] if entry['path'].endswith('.dtb') else prior
        require(all(entry[key] == selected[key] for key in ('bytes', 'sha256', 'crc32')), 'RSCE content policy: ' + entry['path'])
    require(report['components'][2]['bytes'] == end, 'RSCE exact extent policy')
    expected_raw = header['page_size'] + sum((component['bytes'] + header['page_size'] - 1) & ~(header['page_size'] - 1)
                                            for component in report['components'])
    require(report['raw_bytes'] == expected_raw <= SIZE, 'Dynamic raw extent policy')
    sizes = {component['name']: component['bytes'] for component in report['components']}
    plan = image_plan(image_inputs['kernel'], header, sizes)
    semantic = modules['dt-semantics-v2.py']
    baseline, shim = semantic.parse(fixed['audio_baseline']), semantic.parse(fixed['dtb'])
    shim_diff = {'/__symbols__:chosen': {'before': None, 'after': b'/chosen\0'.hex()},
                 '/chosen:phandle': {'before': None, 'after': '000002fa'}}
    require(semantic.diff(baseline, shim) == shim_diff, 'Exactly two audio shim prerequisites')
    handles = semantic.phandles(baseline)
    require(len(baseline['nodes']) == 962 and len(handles) == 761 and max(handles) == 0x2f9 and
            semantic.phandles(shim)[0x2fa] == '/chosen', 'Audio phandle/count policy')
    bridge = modules['libfdt-v2.py']
    entry = modules['build-uart-shim-v2.py'].overlay_entry(fixed['dtbo'])
    apply_report, applied = bridge.RealLibFdt().apply(fixed['dtb'], entry)
    require(apply_report['status'] == 0 and applied is not None, 'Real libfdt audio overlay')
    require((len(applied), metadata(applied)['sha256']) == APPLIED, 'Applied audit-only DT identity')
    tree = semantic.parse(applied)
    reboot = [key.rsplit(':', 1)[0] for key in baseline['properties'] if key.endswith(':mode-normal')]
    require(len(reboot) == 1, 'Unique normal reboot node')
    difference = semantic.overlay_diff(reboot[0])
    difference['/chosen:phandle'] = shim_diff['/chosen:phandle']
    require(semantic.diff(baseline, tree) == difference and tree['properties'][reboot[0] + ':mode-normal'] == '5242c300',
            'Complete five-property audio overlay transition')
    require(all(semantic.phandles(tree).get(handle) == name for handle, name in handles.items()),
            'Existing phandles preserved')
    report.update({'mode': image_inputs['mode'], 'board_tested': False, 'deployed': False,
                   'flash_authorized': False, 'saveenv': False, 'formal_flash_ready': False,
                   'usb_recovery_confirmed': False, 'package_early_dt_compatibility_verified': False,
                   'early_uboot_dtb': 'UNCHANGED_EMMC_ORIGINAL_FOR_RAM_TRIAL',
                   'address_analysis': plan, 'rootfs': metadata(fixed['rootfs']),
                   'native_pid1_old_rcu_image_check_is_new_image_identity': False,
                   'real_overlay': {'apply': apply_report, 'full_semantic_diff': difference,
                                    'applied_audit_only': metadata(applied), 'libfdt_sha256': bridge.LIB_SHA},
                   'packaged_dtb_is_pre_overlay_shim': True,
                   'dependency_files': {name: metadata(blob) for name, blob in checked.items()}})
    return report


def fresh_directory(output):
    path = Path(output).absolute()
    require(path == path.resolve() and path.is_relative_to(HERE / 'build') and path != HERE / 'build',
            'Fresh ordinary output inside own build required')
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_new(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def json_bytes(value):
    return (json.dumps(value, indent=2) + '\n').encode('utf-8')


def construct_package(out, image_inputs):
    """Internal mechanical path shared by the production CLI and labeled test fixtures."""
    modules, checked = dependencies()
    fixed = fixed_inputs()
    original = modules['audit-boot.py'].inspect_boot(fixed['original'])
    payloads = {'kernel': image_inputs['kernel'], 'ramdisk': fixed['ramdisk'], 'dtb': fixed['dtb']}
    payloads['second'] = modules['build-ram-candidate-v2.py'].build_resource(fixed['original'], original, fixed['dtb'])
    image_plan(payloads['kernel'], original['header'], {name: len(blob) for name, blob in payloads.items()})
    projected = 2048 + sum((len(blob) + 2047) & ~2047 for blob in payloads.values())
    require(projected <= SIZE, 'Audio package exceeds 40 MiB')
    output = fresh_directory(out)
    components = output / 'components'
    components.mkdir()
    for name, blob in payloads.items():
        write_new(components / name, blob)
    official = modules['build-roundtrip.py'].official_module(relative_path(PACKAGE + 'sources/mkbootimg.py'))
    header = original['header']
    with ExitStack() as stack:
        stream = stack.enter_context((output / 'boot-raw.img').open('xb'))
        files = {name: stack.enter_context((components / name).open('rb')) for name in payloads}
        args = SimpleNamespace(output=stream, **files, recovery_dtbo=None, header_version=2,
                               pagesize=2048, base=0, kernel_offset=header['kernel_addr'],
                               ramdisk_offset=header['ramdisk_addr'], second_offset=header['second_addr'],
                               tags_offset=header['tags_addr'], dtb_offset=header['dtb_addr'],
                               os_version=header['os_version'], os_patch_level=header['os_patch_level'],
                               board=header['board'], cmdline=CMDLINE)
        official.write_header(args)
        official.write_data(args, 2048)
        stream.flush()
        os.fsync(stream.fileno())
    raw = read_ordinary(output / 'boot-raw.img')
    require(len(raw) == projected, 'Official writer raw extent disagreement')
    padded = raw + bytes(SIZE - len(raw))
    report = inspect_candidate(padded, image_inputs)
    write_new(output / 'boot-padded.img', padded)
    write_new(output / 'audit.json', json_bytes(report))
    snapshot = output / 'source-inputs'
    snapshot.mkdir()
    snapshots = dict(checked)
    for name in ('audio-package-v2.py', 'build-audio-package-v2.py', 'audit-audio-package-v2.py',
                 'test-audio-package-v2.py', 'README-v2.md', 'PLAN-v2.md'):
        relative = str((HERE / name).relative_to(ROOT))
        snapshots[relative] = read_ordinary(HERE / name)
    for name, blob in snapshots.items():
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_new(path, blob)
    manifest = {'schema': 1, 'status': image_inputs['mode'], 'board_tested': False, 'deployed': False,
                'flash_authorized': False, 'saveenv': False, 'formal_flash_ready': False,
                'original': {'path': FIXED['original'][0], **metadata(fixed['original'])},
                'inputs': {name: {'path': fields[0], **metadata(fixed[name])} for name, fields in FIXED.items()
                           if name != 'original'}, 'image_input': {key: value for key, value in image_inputs.items() if key != 'kernel'},
                'kernel': metadata(image_inputs['kernel']), 'cmdline': CMDLINE,
                'rootfs_board_path': '/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4',
                'native_pid1_old_rcu_image_check_is_new_image_identity': False,
                'artifacts': {'boot-raw.img': metadata(raw), 'boot-padded.img': metadata(padded)},
                'components': {name: metadata(blob) for name, blob in payloads.items()},
                'official_commit': OFFICIAL_COMMIT, 'official_functions': ['write_header', 'write_data'],
                'source_inputs': {name: metadata(blob) for name, blob in snapshots.items()},
                'address_analysis': report['address_analysis'], 'real_overlay': report['real_overlay'],
                'required_before_execution': ['fresh bdinfo/banks/gd/env', 'fresh reserved/relocation intervals',
                    'full padded SHA/CRC and actual transfer addresses', 'one-argument bootm from main controller'],
                'board_runtime_proof_required': ['final FDT whole tree and overlay', 'new live Image identity',
                    'bounded PCM lifecycle/readonly state', 'ordinary reboot and unchanged protected Android hashes']}
    write_new(output / 'manifest.json', json_bytes(manifest))
    inventory = {str(path.relative_to(output)): metadata(read_ordinary(path))
                 for path in sorted(output.rglob('*')) if path.is_file()}
    receipt = {'schema': 1, 'status': image_inputs['mode'], 'files': inventory,
               'board_tested': False, 'formal_flash_ready': False, 'freeze_scope': 'ALL_FILES_BEFORE_RECEIPT'}
    write_new(output / 'receipt.json', json_bytes(receipt))
    return manifest


def audit_directory(candidate, image_inputs):
    path = Path(candidate).absolute()
    require(path == path.resolve() and path.is_relative_to(HERE / 'build'), 'Own ordinary candidate directory required')
    receipt = unique_json(read_ordinary(path / 'receipt.json', 4 * 1024 * 1024))
    names = {str(item.relative_to(path)) for item in path.rglob('*') if item.is_file() or item.is_symlink()}
    require(names == set(receipt['files']) | {'receipt.json'}, 'Candidate freeze inventory set changed')
    require(receipt['status'] == image_inputs['mode'] and receipt['board_tested'] is False and
            receipt['formal_flash_ready'] is False, 'Candidate receipt mode/boundary')
    for name, info in receipt['files'].items():
        require(str(PurePosixPath(name)) == name and not name.startswith('/') and
                all(part not in ('', '.', '..') for part in name.split('/')), 'Unsafe freeze relative name')
        require(metadata(read_ordinary(path / name)) == info, 'Candidate frozen file changed: ' + name)
    data = read_ordinary(path / 'boot-padded.img')
    report = inspect_candidate(data, image_inputs)
    manifest = unique_json(read_ordinary(path / 'manifest.json', 4 * 1024 * 1024))
    require(type(manifest.get('schema')) is int and manifest['schema'] == 1 and
            all(manifest.get(name) is False for name in ('board_tested', 'deployed', 'flash_authorized',
                                                        'saveenv', 'formal_flash_ready')),
            'Candidate manifest offline-only boundary')
    require(manifest.get('native_pid1_old_rcu_image_check_is_new_image_identity') is False,
            'Candidate manifest old RCU check is not new Image identity')
    require(manifest.get('rootfs_board_path') == '/cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4',
            'Candidate manifest rootfs cache path')
    require(manifest.get('cmdline') == CMDLINE and manifest.get('official_commit') == OFFICIAL_COMMIT and
            manifest.get('official_functions') == ['write_header', 'write_data'],
            'Candidate manifest cmdline/official functions')
    fixed = fixed_inputs()
    require(manifest.get('original') == {'path': FIXED['original'][0], **metadata(fixed['original'])} and
            manifest.get('inputs') == {name: {'path': fields[0], **metadata(fixed[name])}
                                      for name, fields in FIXED.items() if name != 'original'},
            'Candidate manifest fixed input binding')
    expected_image = {key: value for key, value in image_inputs.items() if key != 'kernel'}
    require(manifest['status'] == image_inputs['mode'] and manifest['image_input'] == expected_image and
            manifest['kernel'] == metadata(image_inputs['kernel']), 'Candidate manifest input binding')
    require(manifest['artifacts']['boot-padded.img'] == metadata(data) and
            manifest['artifacts']['boot-raw.img'] == metadata(data[:report['raw_bytes']]), 'Candidate artifact binding')
    require(read_ordinary(path / 'boot-raw.img') == data[:report['raw_bytes']], 'Raw/padded package binding')
    for component in report['components']:
        name = component['name']
        blob = data[component['offset']:component['offset'] + component['bytes']]
        require(read_ordinary(path / 'components' / name) == blob and manifest['components'][name] == metadata(blob),
                'Candidate components binding: ' + name)
    require(manifest['address_analysis'] == report['address_analysis'] and manifest['real_overlay'] == report['real_overlay'],
            'Candidate semantic/address manifest binding')
    _, checked = dependencies()
    expected_sources = {name: metadata(blob) for name, blob in checked.items()}
    for name, blob in checked.items():
        require(read_ordinary(path / 'source-inputs' / name) == blob, 'Locked dependency snapshot binding')
    for name in ('audio-package-v2.py', 'build-audio-package-v2.py', 'audit-audio-package-v2.py', 'test-audio-package-v2.py', 'README-v2.md', 'PLAN-v2.md'):
        relative = str((HERE / name).relative_to(ROOT))
        blob = read_ordinary(HERE / name)
        expected_sources[relative] = metadata(blob)
        require(read_ordinary(path / 'source-inputs' / relative) == blob, 'Current builder/auditor snapshot binding')
    require(manifest.get('source_inputs') == expected_sources, 'Candidate manifest source snapshot metadata')
    report['candidate_manifest'] = metadata(read_ordinary(path / 'manifest.json'))
    report['candidate_receipt'] = metadata(read_ordinary(path / 'receipt.json'))
    return report
