#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline v3 accessory build and immutable receipts; no board access."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = HERE.parent / 'session-guard-v2'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('Missing/nonregular/symlink input: ' + str(path))


def run(out, name, argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    (out / (name + '.stdout')).write_text(result.stdout)
    (out / (name + '.stderr')).write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result


def main():
    out = HERE / 'build'
    out.mkdir(exist_ok=False)
    inputs = HERE / 'inputs'
    inputs.mkdir(exist_ok=False)
    cpu = ROOT / 'outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10/sound/soc/rockchip/rockchip_i2s_tdm.c'
    cpu_manifest = ROOT / 'outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10/manifest.json'
    dma_dir = ROOT / 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/source'
    dma_manifest = dma_dir / 'manifest.json'
    inspector = ROOT / 'outputs/rk3568-audio-20261005/build/inspect-v4/alsa-inspect'
    applets = ROOT / 'outputs/rk3568-persistent-linux-20261003/busybox-applets.txt'
    bb = ROOT / 'outputs/rk3568-rng-network-20261004/build/busybox-module-options/v1/busybox'
    qemu = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
    config = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/integration-v1/kernel.config'
    locks = [(cpu, 'cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59'),
             (inspector, '118cf99482cdd65acdfae8c5e85530a76bf60c90b0b0498e8f285223f862a945'),
             (applets, '6e2d74e972829be2fcacb329bcddd2b5d026a138a76031ae1ad9e5b3dd96eedf'),
             (bb, '514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1')]
    locks.append((config, '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'))
    for path, expected in locks:
        plain(path)
        if sha(path) != expected:
            raise ValueError('Frozen input mismatch: ' + str(path))
    if '# CONFIG_UIO is not set' not in config.read_text().splitlines():
        raise ValueError('This session kernel configuration must explicitly disable UIO')
    manifest = json.loads(dma_manifest.read_text())
    sources = manifest['source_sha256']
    if len(sources) != 13 or sources['drivers/dma/pl330.c'] != 'ac40d2e3c41116667f2ef147b1f644c9782d26cd8f1597628afa67bd50f93b16':
        raise ValueError('Need exact accepted C3 source manifest')
    selected = [cpu, cpu_manifest, dma_manifest, inspector, applets, bb, qemu,
                ROOT / 'outputs/rk3568-audio-20261005/alsa-inspect.c',
                ROOT / 'outputs/rk3568-audio-20261005/build/inspect-v4/manifest.json',
                ROOT / 'outputs/rk3568-audio-runtime-20261005/pcm-config.c',
                ROOT / 'outputs/rk3568-audio-transfer-20261005/pcm-transfer.c',
                ROOT / 'outputs/rk3568-audio-transfer-20261005/build/static-v1/manifest.json',
                ROOT / 'outputs/rk3568-audio-runtime-20261005/INTEGRATION-PLAN.md',
                ROOT / 'third_party/linux-rk3588/drivers/clk/clk.c',
                ROOT / 'third_party/linux-rk3588/arch/arm64/boot/dts/rockchip/rk3568.dtsi',
                ROOT / 'platforms/rk3568/boards/aiot-3568pq/bsp/rk3568-aiot-3568pq-audio.dts']
    selected.extend([config, ROOT / 'third_party/linux-rk3588/drivers/uio/uio.c',
                     ROOT / 'third_party/linux-rk3588/fs/char_dev.c',
                     ROOT / 'third_party/linux-rk3588/fs/proc/devices.c',
                     ROOT / 'third_party/linux-rk3588/include/linux/fs.h',
                     ROOT / 'third_party/linux-rk3588/include/linux/blkdev.h',
                     ROOT / 'third_party/linux-rk3588/fs/file_table.c'])
    selected.append(ROOT / 'outputs/rk3568-pid1-20261005/pid1.c')
    selected.extend(PRIOR / name for name in [
        'audio-session-guard.c', 'guard-parser.h', 'model-driver.c', 'test-models.py',
        'build/manifest.json', 'build/audio-session-guard', 'models/result.json',
        'red-v1/result.json', 'frozen-output-manifest.json', 'SHA256SUMS'])
    for relative, expected in sources.items():
        path = dma_dir / relative
        plain(path)
        if sha(path) != expected:
            raise ValueError('DMA manifest mismatch: ' + relative)
        selected.append(path)
    input_sha = {}
    for path in selected:
        plain(path)
        relative = path.relative_to(ROOT)
        frozen = inputs / relative
        frozen.parent.mkdir(parents=True, exist_ok=True)
        frozen.write_bytes(path.read_bytes())
        input_sha[relative.as_posix()] = sha(frozen)
    actual = run(out, 'busybox52-list', [str(qemu), str(bb), '--list']).stdout.splitlines()
    if actual != applets.read_text().splitlines() or len(actual) != 52:
        raise ValueError('Actual BusyBox52 inventory differs')
    evidence = json.loads((HERE / 'models/result.json').read_text())
    if evidence['parser_sha256'] != sha(HERE / 'guard-parser.h') or not evidence['model_only'] or evidence['board_tested'] or \
            evidence['source_sha256'] != sha(HERE / 'model-driver.c') or evidence['test_sha256'] != sha(HERE / 'test-models.py'):
        raise ValueError('Need fresh offline parser models')
    if len(evidence['targets']) != 3 or any(t['exit'] or t['failures'] or t['cases'] != 501 or t['cases'] != t['passed'] for t in evidence['targets']):
        raise ValueError('Models must pass in all three environments')
    source = HERE / 'audio-session-guard.c'
    prior_source = (PRIOR / source.name).read_bytes()
    old_site = b'canonical_device(argv[4], "fe550000.dma", dma)'
    new_site = b'canonical_device(argv[4], "fe550000.dmac", dma)'
    if prior_source.count(old_site) != 1 or source.read_bytes() != prior_source.replace(old_site, new_site):
        raise ValueError('Production v3 must differ by the exact fixed DMA basename only')
    for name in ['guard-parser.h', 'model-driver.c', 'test-models.py']:
        if (HERE / name).read_bytes() != (PRIOR / name).read_bytes():
            raise ValueError('Existing 501 model/parser contracts must remain byte-exact')
    canonical = json.loads((HERE / 'canonical-models/result.json').read_text())
    red = json.loads((HERE / 'canonical-red-v2/result.json').read_text())
    for receipt, expected_source, red_expected in [
            (canonical, source, False), (red, PRIOR / source.name, True)]:
        if not receipt['model_only'] or receipt['board_tested'] or receipt['expected_red'] != red_expected or \
                receipt['actual_production_source_sha256'] != sha(expected_source) or \
                receipt['model_source_sha256'] != sha(HERE / 'canonical-device-model.c') or \
                receipt['test_sha256'] != sha(HERE / 'test-canonical-device.py') or \
                len(receipt['targets']) != 3:
            raise ValueError('Need fresh actual-production canonical identity models')
        for target in receipt['targets']:
            failures = ['production-fixed-dmac-identity', 'production-reject-old-dma-name'] if red_expected else []
            if target['exit'] or target['cases'] != 13 or target['failures'] != failures or \
                    target['passed'] != (11 if red_expected else 13):
                raise ValueError('Canonical model mismatch')
    obj = out / 'audio-session-guard.o'
    compiler = run(out, 'compiler-version', ['aarch64-linux-gnu-gcc', '--version']).stdout.splitlines()[0]
    compile_argv = ['aarch64-linux-gnu-gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-fno-builtin', '-fno-ident', '-c', str(source), '-o', str(obj)]
    run(out, 'compile', compile_argv)
    imports = run(out, 'object-imports', ['aarch64-linux-gnu-nm', '-u', str(obj)]).stdout
    imported = sorted(line.split()[-1] for line in imports.splitlines() if line.strip())
    forbidden = {'ioctl', 'mmap', 'mount', 'umount', 'umount2', 'reboot', 'system', 'popen',
                 'chmod', 'unlink', 'remove', 'rename', 'kill', 'socket', 'connect', 'write'}
    if forbidden.intersection(imported):
        raise ValueError('Forbidden production import')
    binary = out / 'audio-session-guard'
    link_argv = ['aarch64-linux-gnu-gcc', '-static', '-Wl,--build-id=none', str(obj), '-o', str(binary)]
    run(out, 'link', link_argv)
    data = binary.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', data, 16) != (2, 183):
        raise ValueError('Expected AArch64 static ET_EXEC')
    elf = run(out, 'elf', ['aarch64-linux-gnu-readelf', '-h', '-l', '-d', str(binary)]).stdout
    if 'INTERP' in elf or 'NEEDED' in elf:
        raise ValueError('Dynamic artifact rejected')
    if run(out, 'undefined', ['aarch64-linux-gnu-nm', '-u', str(binary)]).stdout.strip():
        raise ValueError('Unresolved imports')
    prior_binary = PRIOR / 'build/audio-session-guard'
    previous = prior_binary.read_bytes()
    if len(previous) != len(data):
        raise ValueError('Bounded equal-size v2 delta unavailable')
    changed = [index for index, (before, after) in enumerate(zip(previous, data)) if before != after]
    blocks = []
    for offset in changed:
        if blocks and offset == blocks[-1]['offset'] + blocks[-1]['length']:
            blocks[-1]['length'] += 1
        else:
            blocks.append({'offset': offset, 'length': 1})
    for block in blocks:
        start, length = block['offset'], block['length']
        block['before_hex'] = previous[start:start + length].hex()
        block['after_hex'] = data[start:start + length].hex()
    delta = {'board_tested': False, 'applied_on_board': False,
             'v2_bytes': len(previous), 'v3_bytes': len(data),
             'v2_sha256': sha(prior_binary), 'v3_sha256': sha(binary),
             'changed_bytes': len(changed), 'blocks': blocks,
             'block_count': len(blocks),
             'identity_requires_final_full_sha256': True}
    (out / 'v2-binary-delta.json').write_text(json.dumps(delta, indent=2) + '\n')
    rejected = []
    for args in [[], ['--help'], ['both'], ['bound', '8'], ['cpu-unbound', '0', '/missing', '/missing', '/missing']]:
        result = subprocess.run([str(qemu), str(binary), *args], capture_output=True, text=True, timeout=20)
        rejected.append({'arguments': args, 'exit': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode != 2 or result.stdout:
            raise ValueError('Actual production refusal failed')
    receipt = {'board_tested': False, 'model_only': True, 'audio_start_allowed': False,
               'permits_reboot': False, 'published': False, 'deployable': False,
               'binary': binary.name, 'binary_bytes': len(data), 'binary_sha256': sha(binary),
               'binary_crc32': f'{zlib.crc32(data):08x}', 'compiler': compiler,
               'compile_argv': compile_argv, 'link_argv': link_argv,
               'production_object_imports': imported, 'no_pcm_ioctl_pm_mmio_mount_unbind_reboot_operations': True,
               'static': True, 'elf': 'ELF64 LE AArch64 ET_EXEC', 'busybox_actual_applets': actual,
               'busybox_commands_needed': [], 'inspector_sha256': sha(inspector),
               'input_sha256': input_sha, 'model_result_sha256': sha(HERE / 'models/result.json'),
               'v1_alias_red_result_sha256': sha(PRIOR / 'red-v1/result.json'),
               'version': 3, 'fixed_dma_device_basename': 'fe550000.dmac',
               'production_diff_from_v2': 'Exactly one character c in the fixed DMA canonical_device basename; all gates unchanged',
               'prior_v2_source_sha256': sha(PRIOR / source.name),
               'canonical_model_result_sha256': sha(HERE / 'canonical-models/result.json'),
               'canonical_v2_red_result_sha256': sha(HERE / 'canonical-red-v2/result.json'),
               'v2_binary_delta_sha256': sha(out / 'v2-binary-delta.json'),
               'session_config_uio_enabled': False,
               'uio_dynamic_major_source': '/proc/devices Character devices exact registration name uio',
               'uio_major_absence_is_valid': True,
               'fd_domain': 'Top-level PID fd tables only; fresh native single-thread PID1, BusyBox rescue shell and single-thread helper; no product services',
               'inspector_reaped_on_success': True,
               'inspector_reaped_on_failure_or_signal': False,
               'production_argument_refusals': rejected,
               'limitations': ['Models validate parsers, not real hardware stop or runtime collector syscalls',
                               'Two snapshots are not atomic admission; root must prevent concurrent new users',
                               'Different thread files_struct is outside this session domain; no claim of all-thread FD coverage',
                               'Failure or SIGALRM does not prove inspector child cleanup; root must collect evidence and await PID1 adoption/reaping',
                               'UIO alias regression is a general classifier model; session CONFIG_UIO=n does not make it a reachable board fault',
                               'Cached STOP proof is driver-maintained; no new PM/MMIO proof is attempted',
                               'No Image, live FDT, codec ABI, electrical/acoustic, or board verification',
                               'SIGALRM cannot bound uninterruptible kernel wait or an unscheduled process']}
    (out / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    prior_baseline = json.loads((HERE / 'prior-frozen-baseline.json').read_text())['prior_versions']
    verified_prior = {}
    for version, expected in prior_baseline.items():
        directory = HERE.parent / ('session-guard-' + version)
        listing = directory / 'SHA256SUMS'
        count = 0
        if sha(listing) != expected['SHA256SUMS_sha256']:
            raise ValueError('Prior version inventory changed')
        for row in listing.read_text().splitlines():
            expected_sha, relative = row.split('  ', 1)
            path = directory / relative
            plain(path)
            if sha(path) != expected_sha:
                raise ValueError('Prior version contents changed')
            count += 1
        if count != expected['verified_files']:
            raise ValueError('Prior version count changed')
        verified_prior[version] = {'verified_files': count, 'SHA256SUMS_sha256': sha(listing)}
    (HERE / 'prior-frozen-preserved.json').write_text(json.dumps(verified_prior, indent=2) + '\n')
    frozen_files = {p.relative_to(HERE).as_posix(): sha(p) for p in sorted(HERE.rglob('*'))
                    if p.is_file() and p.name not in {'SHA256SUMS', 'frozen-output-manifest.json'}}
    (HERE / 'frozen-output-manifest.json').write_text(json.dumps({'board_tested': False,
                                                                'files_sha256': frozen_files}, indent=2) + '\n')
    frozen_files['frozen-output-manifest.json'] = sha(HERE / 'frozen-output-manifest.json')
    (HERE / 'SHA256SUMS').write_text(''.join(f'{value}  {name}\n' for name, value in sorted(frozen_files.items())))
    print(json.dumps({'binary': str(binary.relative_to(ROOT)), 'bytes': len(data),
                      'sha256': sha(binary), 'inputs': len(input_sha), 'frozen_files': len(frozen_files),
                      'board_tested': False, 'model_only': True}))


if __name__ == '__main__':
    main()
