#!/usr/bin/env python3
"""Prepare SHA-notified sealed v5 files; never connect to or operate the board."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / 'outputs/rk3568-audio-package-20261005/build'
OUT = HERE / 'build/board-audio-v5'
REMOTE = '/cache/rtctrl-audio-bootm-20261005-v5'
IMAGE_SHA = '48b9958d36e2b4821235520360530faac38c9f2dae072c2a2602dbda7e048595'
IMAGE_MANIFEST_SHA = '8df525843cac41fd0e272351bc41d0e573c25570cfed7e60f1990b9fe97aa33a'
CPU_SHA = '7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141'
NATIVE_PID_SHA = '249cc1cfd87cbddc8618e81e6b8fd742526de78fd964d4a4b3b59b8a7d76368b'
GUARD_SHA = '8740384398313be87a13245e854d6fc5a17a10f3794bdd83966e933c894c6f69'
CODEC_MANIFEST_SHA = '32241d1dfe9f2cbf17bae023065d87ee436173ba319a9f40b81ad5c7b1eb8e3c'
CODEC_HELPER_SHA = 'ac8e0fabbb5ee9dee12b136e576560c98e2efe9484727db1227338507a5c1fee'
NOTES_SHA = 'a2008d938402984c29c007a3e2bb229d862776d35ed1bfc3f0246a34650b6436'
NOTES_IDENTITY_SHA = 'bd557ea5160af53ad05e5192e1397eee6046bd2a501acdd65c11ea5fdd064d47'
OLD_BOARD_MANIFEST_SHA = '127e12854aa68fe80aa5655dbea89d86a0b8b1db4f54911610649e585fb4092f'
RUNTIME_FIXED = {
    'snd-soc-rk817.ko': ('outputs/rk3568-audio-runtime-20261005/codec-image-v4-v1/build-v2/modules/snd-soc-rk817.ko',
        519072, 'aa594a46d660c929cdae71f81024659cf9f4beca032baf9a193ad6ded3476171'),
    'alsa-inspect': ('outputs/rk3568-audio-20261005/build/inspect-v4/alsa-inspect', 650408,
        '118cf99482cdd65acdfae8c5e85530a76bf60c90b0b0498e8f285223f862a945'),
    'pcm-transfer': ('outputs/rk3568-audio-transfer-20261005/build/static-v1/pcm-transfer', 659736,
        '2a6c765bd9c3c25b3456e60d68670231e81dcaf7781b827559cd701beed09e2e'),
    'audio-session-guard': ('outputs/rk3568-audio-runtime-20261005/session-guard-v4/build/audio-session-guard', 741560, GUARD_SHA),
    'pcm-peer-idle': ('outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/production-v2/pcm-peer-idle', 655136,
        '7693a052b6318ec3e965451fcb94609e97cb48e693715b847b62032cc684e661'),
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'Exact lowercase full SHA256 required')
    return value


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordinary(path):
    path = Path(path)
    require(path.is_relative_to(ROOT) and '..' not in path.parts, 'Input escaped repository')
    require(stat.S_ISREG(path.lstat().st_mode), 'Input is not an ordinary file: ' + str(path))
    ancestor = path.parent
    while True:
        require(stat.S_ISDIR(ancestor.lstat().st_mode), 'Input ancestor is not ordinary: ' + str(ancestor))
        if ancestor == ROOT:
            break
        ancestor = ancestor.parent
    return path


def relative(name):
    require(isinstance(name, str), 'Relative input path required')
    value = PurePosixPath(name)
    require(name == value.as_posix() and not value.is_absolute() and '..' not in value.parts and '\\' not in name,
            'Canonical repository-relative input required')
    return ROOT / name


def read_json(path, expected=None):
    path = ordinary(path)
    if expected is not None:
        require(sha(path) == digest(expected), 'Input SHA changed: ' + str(path))
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def validate_false_flags(record, keys):
    require(all(record.get(key) is False for key in keys), 'Offline false flags missing or changed')


def full_sha_test(path, expected):
    digest(expected)
    require(re.fullmatch('/[A-Za-z0-9_./-]+', path), 'Fixed shell path required')
    return 'test "$(sha256sum ' + path + ')" = \'' + expected + '  ' + path + "'"


def step(command, expect=None, wait=1):
    require(all(32 <= ord(c) <= 126 for c in command) and 0 <= wait <= 60, 'Console protocol changed')
    value = {'command': command, 'wait': wait}
    if expect:
        value['expect'] = expect
    return value


def validate_current_codec(external_record):
    base = HERE / 'codec-image-v4-v1'
    codec = read_json(base / 'build-v2/manifest.json', CODEC_MANIFEST_SHA)
    validate_false_flags(codec, ['board_tested', 'loaded', 'unload_tested', 'deployed', 'full_duplex_passed', 'accepted_for_board'])
    helper_path = ordinary(base / 'codec_builder.py')
    require(sha(helper_path) == CODEC_HELPER_SHA, 'Reviewed codec inventory helper changed')
    spec = importlib.util.spec_from_file_location('reviewed_v4_codec_helper', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    require(codec['image_sha256'] == IMAGE_SHA and codec['image_manifest_sha256'] == IMAGE_MANIFEST_SHA and
            codec['modversions'] is False and codec['generated_inventory_was_signed_at_Image_compile_time'] is False,
            'Codec Image/profile/snapshot boundary changed')
    root_inventory = read_json(helper.ROOT_ABI / 'inventory.json', helper.ROOT_ABI_INVENTORY_SHA)
    read_json(helper.ROOT_ABI / 'receipt.json', helper.ROOT_ABI_RECEIPT_SHA)
    current = helper.inventory(helper.ABI, helper.COPY_DIRS + helper.COPY_FILES)
    before = read_json(base / 'build-v2/before-ABI.json', codec['ABI_inventory_sha256'])
    require(current == before == read_json(base / 'build-v2/after-ABI.json') and
            current['regular_files_sha256'] == codec['abi_inventory'] and current['regular_file_count'] == 2020,
            'Complete current generated ABI changed')
    for selected in [current, helper.inventory(helper.ROOT_ABI / 'snapshot', helper.COPY_DIRS + helper.COPY_FILES),
                     helper.inventory(base / 'build-v2/kernel-abi', helper.COPY_DIRS + helper.COPY_FILES)]:
        helper.generated_matches_root_snapshot(selected, root_inventory)
    source = helper.inventory(helper.SOURCE, helper.SOURCE_SELECTIONS, True)
    require(source == read_json(base / 'build-v2/before-source-headers-scripts.json', codec['source_inventory_sha256']) ==
            read_json(base / 'build-v2/after-source-headers-scripts.json') and source['regular_file_count'] == 6360 and
            source['known_SDK_internal_links'] == codec['source_known_SDK_links'], 'Codec SOURCE binding changed')
    image = read_json(HERE / 'build/integration-v4/manifest.json', IMAGE_MANIFEST_SHA)
    complete = read_json(HERE / 'build/integration-v4/integrated-source-inventory.json', image['integrated_source_inventory_sha256'])
    helper.source_matches_image_inventory(source, complete, helper.SOURCE_SELECTIONS)
    module_symbols = helper.symbols(helper.ABI / 'Module.symvers')
    vmlinux_symbols = helper.symbols(helper.ABI / 'vmlinux.symvers')
    for name, entry in codec['module']['imports'].items():
        require(module_symbols[name] == vmlinux_symbols[name] == entry, 'Actual import tables changed')
    frozen_external = read_json(base / 'freeze-preflight-v1/external-inputs.json',
        '4a493cab131a387446e8bdd9575b4372fc21ed52232fb4a61cf1e04d344ac83e')
    typed = external_record['typed_SDK_internal_links']
    require(typed == frozen_external['typed_SDK_internal_links'] and
            external_record['typed_link_count'] == len(typed) == 30, 'Final package exact typed link set changed')
    for name, item in typed.items():
        p = relative(name)
        helper.ordinary_directory(p.parent)
        require(stat.S_ISLNK(p.lstat().st_mode) and str(p.readlink()) == item['link_text'] and
                hashlib.sha256(item['link_text'].encode()).hexdigest() == item['link_text_sha256'], 'Typed link identity changed')
        if p.is_relative_to(helper.SOURCE):
            require(source['known_SDK_internal_links'][p.relative_to(helper.SOURCE).as_posix()] == item,
                    'SOURCE typed link differs from actual validated record')
        else:
            original = ROOT / 'third_party/linux-rk3588'
            require(p.is_relative_to(original) and
                    helper.inspect_DTC_prefix_link(original, p.relative_to(original).as_posix()) == item,
                    'Original SDK typed link changed')
    negative = external_record['negative_fixture_link_targets_not_followed']
    require(isinstance(negative, dict) and len(negative) == 2, 'Exact two existing rejected link fixtures required')
    for name, text in negative.items():
        p = relative(name)
        helper.ordinary_directory(p.parent)
        require(stat.S_ISLNK(p.lstat().st_mode) and str(p.readlink()) == text, 'Rejected fixture link text/type changed')
        # These rejected test inputs are not resolved and never become board inputs.
    return {'current_generated_ABI_files': 2020, 'current_SOURCE_regular_files': 6360,
            'current_SOURCE_file_links': 4, 'current_SOURCE_directory_links': 13,
            'external_typed_links_checked': len(typed), 'negative_fixture_links_not_followed': len(negative),
            'directory_link_contents_traversed': False, 'generated_inventory_was_signed_at_Image_compile_time': False}


def validate_inputs(args):
    seal = PACKAGE / 'sealed-production-v5'
    receipt = read_json(seal / 'receipt.json', args.sealed_receipt_sha256)
    require(receipt['status'] == 'RAM_ONLY_NOT_FLASH_READY', 'Final RAM-only package receipt required')
    validate_false_flags(receipt, ['board_tested', 'physical_sound_verified', 'formal_flash_ready'])
    frozen = read_json(seal / 'frozen-output-manifest.json', args.sealed_inventory_sha256)
    validate_false_flags(frozen, ['board_tested'])
    require(isinstance(frozen.get('files_sha256'), dict) and frozen['files_sha256'], 'Final complete seal inventory required')
    for name, expected in frozen['files_sha256'].items():
        relative_name = PurePosixPath(name)
        require(not relative_name.is_absolute() and '..' not in relative_name.parts and name == relative_name.as_posix(), 'Seal path escaped')
        require(sha(ordinary(seal / name)) == digest(expected), 'Sealed file changed: ' + name)
    sums = ordinary(seal / 'SHA256SUMS')
    require(sha(sums) == digest(args.sealed_sums_sha256), 'Final SUM identity changed')
    entries = {}
    for line in sums.read_text().splitlines():
        expected, name = line.split('  ', 1)
        require(name not in entries, 'Duplicate SUM row')
        entries[name] = digest(expected)
    require(entries == {**frozen['files_sha256'], 'frozen-output-manifest.json': digest(args.sealed_inventory_sha256)},
            'Exact final SUM rows changed')
    actual_seal_files = set()
    for p in seal.rglob('*'):
        mode = p.lstat().st_mode
        require(stat.S_ISDIR(mode) or stat.S_ISREG(mode), 'Nonordinary final seal member')
        if stat.S_ISREG(mode):
            ordinary(p)
            actual_seal_files.add(p.relative_to(seal).as_posix())
    require(actual_seal_files == set(frozen['files_sha256']) | {'frozen-output-manifest.json', 'SHA256SUMS'},
            'Complete final seal ordinary set changed')
    external_record = read_json(seal / 'external-evidence.json', args.external_evidence_sha256)
    external = external_record['files']
    require(isinstance(external, dict) and external, 'Complete external ordinary inputs required')
    for name, entry in external.items():
        p = ordinary(relative(name))
        require(p.stat().st_size == entry['bytes'] and sha(p) == digest(entry['sha256']), 'External evidence changed: ' + name)
    bundle_path = PACKAGE / 'ram-audio-v5'
    bundle = read_json(bundle_path / 'manifest.json', receipt['manifest']['sha256'])
    package_receipt = read_json(bundle_path / 'receipt.json', receipt['package_receipt']['sha256'])
    for item in [bundle, package_receipt]:
        require(item['status'] == 'RAM_ONLY_NOT_FLASH_READY', 'Actual bundle RAM-only mode required')
        validate_false_flags(item, ['board_tested', 'formal_flash_ready'])
    validate_false_flags(bundle, ['deployed', 'flash_authorized', 'saveenv'])
    require(bundle['native_pid1_old_rcu_image_check_is_new_image_identity'] is False, 'Native old check is not new Image identity')
    root_audit = PACKAGE / 'audit-root-v5/receipt.json'
    root_record = read_json(root_audit, receipt['root_fresh_audit_receipt']['sha256'])
    require(root_record['mode'] == 'PRODUCTION_AUDIO_RAM_OFFLINE_AUDIT_ONLY', 'Root fresh package audit required')
    package = ordinary(bundle_path / 'boot-padded.img')
    blob = package.read_bytes()
    require(len(blob) == 41943040 and sha(package) == receipt['package']['boot-padded.img']['sha256'] ==
            bundle['artifacts']['boot-padded.img']['sha256'], 'Full 40MiB package SHA/size changed')
    tool = ROOT / 'outputs/rk3568-audio-package-20261005/audio-package-v5.py'
    require(sha(ordinary(tool)) == digest(args.package_tool_sha256) == receipt['core_sha256'], 'Final package tool binding changed')
    require(tool.relative_to(ROOT).as_posix() in external, 'Actual package tool missing from external evidence')
    image = read_json(HERE / 'build/integration-v4/manifest.json', IMAGE_MANIFEST_SHA)
    require(image['build_exit_code'] == 0 and image['image_sha256'] == IMAGE_SHA and image['cpu_source_sha256'] == CPU_SHA and
            sha(ordinary(HERE / 'build/integration-v4/Image')) == IMAGE_SHA, 'Actual accepted Image binding changed')
    validate_false_flags(image, ['battery_algorithm_enabled', 'compressed_audio_enabled', 'duplex_START_gates_relaxed'])
    runtime_record = bundle['image_input']['runtime']
    validate_false_flags(runtime_record, ['board_tested', 'physical_sound_verified', 'formal_flash_ready'])
    require(runtime_record['cpu_source_sha256'] == CPU_SHA and runtime_record['cpu_version'] == 12 and
            runtime_record['guard_version'] == 4 and runtime_record['guard_is_collector_not_START_authorization'] is True,
            'CPU/guard version boundary changed')
    runtime = runtime_record['files']
    require(set(runtime) == set(RUNTIME_FIXED), 'Exact five runtime sidecars required')
    for name, (original, size, expected) in RUNTIME_FIXED.items():
        item = runtime[name]
        source = ordinary(relative(original))
        sidecar = ordinary(bundle_path / 'runtime' / name)
        require(item['path'] == original and item['bytes'] == size and item['sha256'] == expected and
                source.stat().st_size == sidecar.stat().st_size == size and sha(source) == sha(sidecar) == expected and
                source.read_bytes() == sidecar.read_bytes(), 'Runtime original/sidecar changed: ' + name)
        require(external.get(sidecar.relative_to(ROOT).as_posix()) == {'bytes': size, 'sha256': expected},
                'Runtime sidecar not in final external evidence: ' + name)
        require(original in external, 'Runtime original missing external source binding: ' + name)
    notes = read_json(HERE / 'build/live-image-v4-id/identity.json', NOTES_IDENTITY_SHA)
    require(notes['image_sha256'] == IMAGE_SHA and notes['image_manifest_sha256'] == IMAGE_MANIFEST_SHA and
            notes['notes_bytes'] == 60 and notes['notes_sha256'] == NOTES_SHA and notes['board_verified'] is False,
            'New actual notes identity changed')
    old = read_json(HERE / 'build/board-audio-v4/input-manifest.json', OLD_BOARD_MANIFEST_SHA)
    require(len(old['protected_sha256']) == 7 and len(old['native_cached_sha256']) == 3, 'Original protection/native set changed')
    require(sha(ordinary(HERE / 'build/audio-ram-shim-v1/applied-audit-only.dtb')) ==
            '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f', 'Accepted audio DT changed')
    codec_proof = validate_current_codec(external_record)
    return receipt, frozen, external, bundle, package_receipt, root_audit, package, blob, runtime, old, codec_proof


def stage_script(runtime):
    backing = '/.backing-cache' + REMOTE[len('/cache'):]
    script = '''#!/bin/sh
set -eu
uid_fields=$(grep '^Uid:' /proc/self/status)
set -- $uid_fields
test "$#" = 5
test "$2:$3:$4:$5" = 0:0:0:0
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/pid1
'''
    script += full_sha_test('/proc/1/exe', NATIVE_PID_SHA) + '\n'
    script += full_sha_test('/sys/kernel/notes', NOTES_SHA) + '\n'
    script += '''test -z "$(cat /proc/modules)"
test ! -e /tmp/audio
test ! -L /tmp/audio
test ! -e /dev/McuCom
'''
    for name, item in runtime.items():
        script += full_sha_test(backing + '/' + name, item['sha256']) + '\n'
    script += 'mkdir -m 700 /tmp/audio\n'
    for name, item in runtime.items():
        destination = 'audio-session-guard-v4' if name == 'audio-session-guard' else name
        script += 'cp ' + backing + '/' + name + ' /tmp/audio/' + destination + '\n'
        script += full_sha_test('/tmp/audio/' + destination, item['sha256']) + '\n'
    script += 'chmod 500 /tmp/audio/alsa-inspect /tmp/audio/pcm-transfer /tmp/audio/audio-session-guard-v4 /tmp/audio/pcm-peer-idle\n'
    script += 'echo AUDIO_PACKAGE_V5_RAM_AUX_VERIFIED_NO_MODULE_OR_START\n'
    return script.encode('ascii'), backing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['sealed-receipt', 'sealed-inventory', 'sealed-sums', 'external-evidence', 'package-tool']:
        parser.add_argument('--' + name + '-sha256', type=digest, required=True)
    args = parser.parse_args()
    receipt, frozen, external, bundle, package_receipt, root_audit, package, blob, runtime, old, codec_proof = validate_inputs(args)
    require(not OUT.exists() and not OUT.is_symlink(), 'Fresh board-audio-v5 output required')
    ordinary(HERE / 'build/board-audio-v4/input-manifest.json')
    OUT.mkdir()
    def write(name, value):
        data = value if isinstance(value, bytes) else (json.dumps(value, indent=2) + '\n').encode()
        with (OUT / name).open('xb') as stream:
            stream.write(data)
    files = {'boot-audio.img': package, **{name: ordinary(relative(item['path'])) for name, item in runtime.items()}}
    data, backing = stage_script(runtime)
    write('stage-aux.sh', data)
    files['stage-aux.sh'] = OUT / 'stage-aux.sh'
    write('audio-files.sha256', ''.join(sha(path) + '  ' + name + '\n' for name, path in files.items() if name != 'boot-audio.img').encode())
    files['audio-files.sha256'] = OUT / 'audio-files.sha256'
    manifest = {'host_verified': True, 'mode': 'RAM_ONLY_NOT_FLASH_READY',
        'files': [{'name': name, 'source': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                  for name, path in files.items()], 'remote': REMOTE, 'backing_cache': backing,
        'protected_sha256': old['protected_sha256'], 'native_cached_sha256': old['native_cached_sha256'],
        'sealed_package_receipt_sha256': args.sealed_receipt_sha256, 'sealed_inventory_sha256': args.sealed_inventory_sha256,
        'sealed_sums_sha256': args.sealed_sums_sha256, 'external_evidence_sha256': args.external_evidence_sha256,
        'sealed_files_checked': len(frozen['files_sha256']), 'external_evidence_files_checked': len(external),
        'package_manifest_sha256': sha(PACKAGE / 'ram-audio-v5/manifest.json'),
        'package_receipt_sha256': sha(PACKAGE / 'ram-audio-v5/receipt.json'), 'root_fresh_audit_receipt_sha256': sha(root_audit),
        'image_sha256': IMAGE_SHA, 'image_manifest_sha256': IMAGE_MANIFEST_SHA, 'cpu_source_sha256': CPU_SHA,
        'guard_binary_sha256': GUARD_SHA, 'peer_binary_sha256': RUNTIME_FIXED['pcm-peer-idle'][2],
        'notes_identity_sha256': NOTES_IDENTITY_SHA, 'notes_sha256': NOTES_SHA, 'codec_manifest_sha256': CODEC_MANIFEST_SHA,
        'current_codec_proof': codec_proof, 'package_tool_sha256': args.package_tool_sha256,
        'builder_sha256': sha(Path(__file__)), 'board_tested': False, 'start_allowed': False,
        'battery_algorithm_enabled': False, 'usb_peripheral_enabled': False, 'early_emmc_candidate_included': False}
    write('input-manifest.json', manifest)
    crc = f'{zlib.crc32(blob):08x}'
    write('load.json', [step('bdinfo', wait=2),
        step('printenv kernel_addr_r fdt_addr_r ramdisk_addr_r initrd_high fdt_high bootargs', wait=2),
        step('ext4load mmc 0:c 20000000 ' + REMOTE[len('/cache'):] + '/boot-audio.img', '41943040 bytes read', 5),
        step('printenv filesize', r'filesize=0x2800000'), step('crc32 20000000 2800000', r'227fffff ==> ' + crc, 3)])
    write('boot.json', [step('setenv initrd_high ffffffffffffffff'), step('setenv fdt_high ffffffffffffffff'),
        step('setenv kernel_addr_r 400000'), step('setenv ramdisk_addr_r 4000000'), step('setenv fdt_addr_r a100000'),
        step('printenv kernel_addr_r fdt_addr_r ramdisk_addr_r initrd_high fdt_high'),
        step('bootm 20000000', r'(?m)^LINUX_PID1_ROOT_READY\r?$', 45)])
    target = '/tmp/audio-stage-package-v5.sh'
    steps = [step('test ! -e ' + target + ' && test ! -L ' + target + ' && echo AUDIO_STAGE_PACKAGE_V5_ABSENT',
                  r'(?m)^AUDIO_STAGE_PACKAGE_V5_ABSENT\r?$')]
    for offset in range(0, len(data), 96):
        encoded = ''.join('\\0' + f'{byte:03o}' for byte in data[offset:offset + 96])
        steps.append(step("printf '%b' '" + encoded + "' " + ('>' if offset == 0 else '>>') + ' ' + target, wait=0.05))
    steps.append(step(full_sha_test(target, sha(OUT / 'stage-aux.sh')) + ' && sh ' + target,
                      r'(?m)^AUDIO_PACKAGE_V5_RAM_AUX_VERIFIED_NO_MODULE_OR_START\r?$', 5))
    write('copy-aux.json', steps)
    print(json.dumps({'files': len(files), 'package_crc32': crc, 'manifest_sha256': sha(OUT / 'input-manifest.json'),
                      'board_tested': False, 'start_allowed': False}))


if __name__ == '__main__':
    main()
