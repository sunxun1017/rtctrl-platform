#!/usr/bin/env python3
"""Primary-agent read-only verification of all candidate-v2 frozen receipt files."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCE = ROOT / 'outputs/rk3568-boot-package-20261005'
FROZEN = SOURCE / 'build/candidate-freeze-v2'
PACKAGE = SOURCE / 'build/ram-candidate-v2'


def verify(path, expected):
    data = path.read_bytes()
    actual = {
        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
        'crc32': f'{zlib.crc32(data) & 0xffffffff:08x}',
    }
    if any(actual[key] != expected[key] for key in actual):
        raise ValueError('Frozen file mismatch: ' + str(path))
    return actual


def main():
    output = HERE / 'candidate-v2-input-review-v1.json'
    if output.exists():
        raise ValueError('Refusing to overwrite review')
    receipt_path = FROZEN / 'receipt.json'
    receipt_bytes = receipt_path.read_bytes()
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    if receipt_sha != '5a928d8c2acbe4f71b73e20890750122876804934f3f63dc3b04cd7fdddfcf73':
        raise ValueError('Frozen receipt mismatch')
    receipt = json.loads(receipt_bytes)
    checked = {}
    for relative, expected in receipt['source_snapshot'].items():
        checked['source-snapshot/' + relative] = verify(FROZEN / 'source-snapshot' / relative, expected)
    for relative, expected in receipt['evidence'].items():
        checked[relative] = verify(ROOT / relative, expected)
    for name, expected in receipt['artifacts'].items():
        checked['package/' + name] = verify(PACKAGE / name, expected)
    for name, expected in {**receipt['inputs'], 'rootfs': receipt['rootfs']}.items():
        checked['input/' + name] = verify(ROOT / expected['path'], expected)
    for name, expected in receipt['old_receipts_verified_unchanged'].items():
        checked['old-receipt/' + name] = verify(SOURCE / 'build' / name / 'receipt.json', expected)
    original = ROOT / 'outputs/rk3568-backup-linux-20261003/original'
    checked['original/boot.img'] = verify(original / 'boot.img', receipt['original_boot_unchanged'])
    checked['original/dtbo.img'] = verify(original / 'dtbo.img', receipt['original_dtbo'])
    checked['applied-audit-only'] = verify(ROOT / receipt['applied_audit_only_path'], receipt['real_overlay']['applied_audit_only'])
    package = (PACKAGE / 'boot-padded.img').read_bytes()
    if package[:8] != b'ANDROID!' or struct.unpack_from('<I', package, 40)[0] != 2:
        raise ValueError('Wrong Android header')
    if len(package) != 41943040 or any(package[40478720:]):
        raise ValueError('Wrong full package or nonzero tail')
    if receipt['packaged_dtb_is_pre_overlay_shim'] is not True or receipt['flash_authorized'] is not False:
        raise ValueError('Wrong RAM-only contract')
    result = {
        'status': 'FROZEN_CANDIDATE_V2_INPUT_REVIEW_PASSED',
        'receipt_sha256': receipt_sha, 'checked_receipt_files': len(checked), 'checked': checked,
        'package': checked['package/boot-padded.img'],
        'semantic_independent_review_completed': False,
        'actual_board_bootm_performed': False, 'flash_performed': False,
    }
    with output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: result[key] for key in ('status', 'checked_receipt_files', 'package')}))


if __name__ == '__main__':
    main()
