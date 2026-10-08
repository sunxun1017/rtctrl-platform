#!/usr/bin/env python3
"""Finite full-file readback for this separate package; final acceptance is root's."""
import argparse
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('offline_readback', HERE / 'offline-next.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', default='package-v1')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    package = HERE / args.package
    tool.require(package == package.resolve() and package.is_relative_to(HERE), 'Own ordinary package path')
    receipt_bytes = tool.read(package / 'receipt.json')
    receipt = tool.unique_json(receipt_bytes)
    files = receipt['files_before_receipt']
    actual = set()
    for p in package.rglob('*'):
        tool.require(not p.is_symlink() and (p.is_file() or p.is_dir()), 'Ordinary full bundle members')
        if p.is_file():
            actual.add(p.relative_to(package).as_posix())
    tool.require(actual == set(files) | {'receipt.json'} and len(files) == receipt['complete_file_count_excluding_receipt'],
                 'Complete exact package file set')
    for name, expected in files.items():
        tool.require(tool.metadata(tool.read(package / name)) == expected, 'Complete bundle byte drift: ' + name)
    manifest = tool.unique_json(tool.read(package / 'manifest.json'))
    tool.require(manifest['mode'] == receipt['mode'] == tool.MODE and manifest['offline_format_constructed'] is True and
                 all(manifest[k] is False for k in ('board_tested', 'START_authorized', 'loaded', 'deployed',
                     'full_duplex_passed', 'physical_audio_verified', 'flash_ready', 'formal_flash_ready',
                     'saveenv', 'TUN_modified', 'full_migration_completed', 'old_v5_production_acceptance_gate_used',
                     'root_independent_review_completed_by_this_tool')), 'Explicit candidate acceptance boundary')
    modules, unused = tool.dependencies()
    original = modules['audit-boot.py'].inspect_boot(tool.locked(*tool.FIXED['original_boot']))
    payloads = {n: tool.read(package / 'components' / n) for n in ('kernel', 'ramdisk', 'second', 'dtb')}
    padded = tool.read(package / 'boot-padded.img')
    raw = tool.read(package / 'boot-raw.img')
    audit = tool.inspect_padded(padded, payloads, original, modules, manifest['complete_DT'])
    tool.require(len(raw) == audit['raw_bytes'] and padded == raw + bytes(tool.SIZE - len(raw)), 'Exact full raw/padded relation')
    tool.require(audit == tool.unique_json(tool.read(package / 'audit.json')), 'Complete package fresh audit equals saved audit')
    candidate, applied, entry, dt = tool.prepare_dt(tool.locked(*tool.FIXED['prior_shim']),
        tool.locked(*tool.FIXED['original_dtbo']), modules)
    tool.require(candidate == payloads['dtb'] and applied == tool.read(package / 'applied-audit-only.dtb') and
                 entry == tool.read(package / 'overlay-entry0.dtbo') and dt == manifest['complete_DT'], 'Fresh real overlay complete equality')
    for n, identity in tool.RUNTIME_FIXED.items():
        tool.require(tool.read(package / 'runtime' / n) == tool.locked(*identity), 'Exact retained sidecar: ' + n)
    tool.require(tool.read(package / 'runtime/snd-soc-rk817.ko') == tool.locked(*tool.NEW['codec']), 'Exact canonical codec sidecar')
    sums = ''.join(tool.metadata(tool.read(package / 'runtime' / n))['sha256'] + '  ' + n + '\n'
                   for n in sorted(manifest['runtime'])).encode()
    tool.require(tool.read(package / 'runtime/SHA256SUMS') == sums, 'Complete runtime SHA256SUMS')
    tool.require(tool.read(package / 'rootfs-pid1.ext4') == tool.locked(*tool.FIXED['rootfs']) and
                 payloads['ramdisk'] == tool.locked(*tool.FIXED['ramdisk']), 'Identical prior rootfs/initramfs')
    result = {'scope': 'finite_complete_offline_bundle_readback_no_board_or_global_source_reaudit',
        'receipt': tool.metadata(receipt_bytes), 'complete_files_verified_excluding_receipt': len(files),
        'all_full_bytes_sha_crc_match': True, 'fresh_format_and_real_overlay_equal_saved': True,
        'raw': tool.metadata(raw), 'padded': tool.metadata(padded), 'runtime_files': len(manifest['runtime']),
        'new_DT': tool.metadata(candidate), 'rootfs_and_initramfs_identical_prior': True,
        'source_independent_review_is_root_responsibility': True, 'board_tested': False,
        'START_authorized': False, 'formal_flash_ready': False}
    output = HERE / args.out
    tool.require(output == output.resolve() and output.is_relative_to(HERE), 'Own fresh result required')
    tool.write_new(output, tool.json_bytes(result))
    print(tool.json_bytes(result).decode())


if __name__ == '__main__':
    main()
