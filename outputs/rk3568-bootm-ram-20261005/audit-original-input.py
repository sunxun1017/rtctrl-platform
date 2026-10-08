#!/usr/bin/env python3
"""Read-only primary-agent verification of the frozen original RAM boot input."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCE = ROOT / 'outputs/rk3568-boot-package-20261005'
FROZEN = SOURCE / 'build/original-freeze-v1'
EXPECTED = '0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    output = HERE / 'original-input-review-v1.json'
    if output.exists():
        raise ValueError('Refusing to overwrite review')
    receipt_bytes = (FROZEN / 'receipt.json').read_bytes()
    assert sha(receipt_bytes) == '1349c5668bc8b84aa7d74c83a808c216bf16d967ac5ac14ae01f8bb8ac7eb6e9'
    receipt = json.loads(receipt_bytes)
    checked = {}
    for name, expected in receipt['source_snapshot'].items():
        data = (FROZEN / 'source-snapshot' / name).read_bytes()
        assert len(data) == expected['bytes'] and sha(data) == expected['sha256'], name
        checked['source-snapshot/' + name] = expected
    for name, expected in receipt['evidence'].items():
        data = (ROOT / name).read_bytes()
        assert len(data) == expected['bytes'] and sha(data) == expected['sha256'], name
        checked[name] = expected
    manifest_bytes = (FROZEN / 'original-ram-manifest-v1.json').read_bytes()
    assert sha(manifest_bytes) == '68f16cc3d2ae80e315d3787e04f99e87b8458c90321b7bcee41a94ac370f6cb2'
    manifest = json.loads(manifest_bytes)
    original = (ROOT / 'outputs/rk3568-backup-linux-20261003/original/boot.img').read_bytes()
    candidate = (ROOT / manifest['package_path']).read_bytes()
    assert len(original) == len(candidate) == 41943040
    assert original == candidate and sha(candidate) == EXPECTED
    assert zlib.crc32(candidate) & 0xffffffff == 0x6e48ba06
    assert candidate[:8] == b'ANDROID!'
    kernel_size, kernel_addr, initrd_size, initrd_addr, second_size, second_addr, tags_addr, page, version = struct.unpack_from('<9I', candidate, 8)
    assert (kernel_size, initrd_size, second_size, page, version) == (33046536, 822304, 4491776, 2048, 2)
    assert not any(candidate[40019968:])
    result = {'status': 'FROZEN_ORIGINAL_INPUT_REVIEW_PASSED', 'checked_receipt_files': len(checked),
              'checked': checked, 'package': {'bytes': len(candidate), 'sha256': sha(candidate), 'crc32': '6e48ba06'},
              'byte_identical_to_original_backup': True, 'header_addresses_metadata_only': {
                  'kernel': hex(kernel_addr), 'ramdisk': hex(initrd_addr), 'second': hex(second_addr), 'tags': hex(tags_addr)},
              'ram_boot_arity': 1, 'actual_board_bootm_performed': False, 'flash_performed': False,
              'source_compatibility_claim': 'Rockchip public reference is not exact SMDT U-Boot; original package identity only'}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('status', 'checked_receipt_files', 'package')}))


if __name__ == '__main__':
    main()
