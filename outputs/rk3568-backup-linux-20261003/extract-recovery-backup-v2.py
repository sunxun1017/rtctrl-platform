#!/usr/bin/env python3
"""Extract a fully hashed partition from the retained exec-out stream.

This Android's legacy exec-out transport merges remote stderr with stdout.
The original stream is kept byte for byte; only its verified 96 MiB prefix
is the partition image. No board command or partition write occurs here.
"""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SIZE = 100663296
EXPECTED = 'a94f4e7f0180844aa9ec67253276879f7407c9a85d2138c7636d764048890933'
PROTECTED = [
    ('0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28', '/dev/block/by-name/boot'),
    ('4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e', '/dev/block/by-name/uboot'),
    ('bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8', '/dev/block/by-name/trust'),
    ('59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d', '/dev/block/by-name/dtbo'),
    ('76ff77959f2451ee3838de5b2d90a0e21017345cac4f7ce56c9da7a630edc752', '/dev/block/by-name/vbmeta'),
    ('4fcebae566d889072954b2f5b220474fe9accd75bbb48471023f24841b6ed95e', '/cache/rtctrl-source-userspace-20261004/rootfs.ext4'),
    ('32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3', '/cache/rtctrl-network-rootfs-20261004/rootfs.img'),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    out = HERE / 'original/recovery.img'
    report = HERE / 'recovery-backup-v2.json'
    tail_path = HERE / 'recovery-transfer-diagnostics-v2.txt'
    if any(p.exists() for p in (out, report, tail_path)):
        raise ValueError('Fresh host outputs required')
    first = json.loads((HERE / 'recovery-backup-v1.json').read_text())
    after = json.loads((HERE / 'recovery-fresh-after-v2.json').read_text())
    sec = after['sections']
    if any(x['exit_code'] != 0 for x in sec.values()):
        raise ValueError('Fresh board check failed')
    if sec['fresh_android']['output'].strip() != '0\n4.19.232\n11\n1':
        raise ValueError('Unexpected board identity')
    if sec['bytes_after']['output'].strip() != str(SIZE):
        raise ValueError('Partition size changed')
    expected_line = EXPECTED + '  /dev/block/by-name/recovery'
    if first['sections']['sha_before']['output'].strip() != expected_line or sec['sha_after']['output'].strip() != expected_line:
        raise ValueError('Before/after partition SHA differs')
    expected_protected = '\n'.join(a + '  ' + b for a, b in PROTECTED)
    if sec['seven_protected_sha_after']['output'].strip() != expected_protected:
        raise ValueError('Protected input changed')
    raw = (HERE / 'original/recovery.img.partial').read_bytes()
    core, tail = raw[:SIZE], raw[SIZE:]
    if len(core) != SIZE or sha(core) != EXPECTED or core[:8] != b'ANDROID!':
        raise ValueError('Full partition prefix hash/header failed')
    pattern = rb'96\+0 records in\n96\+0 records out\n100663296 bytes \(96 M\) copied, [0-9.]+ s, [0-9.]+ K/s\n'
    if len(raw) != first['copied_bytes'] or first['sections']['transfer']['exit_code'] != 0 or not re.fullmatch(pattern, tail):
        raise ValueError('Unexpected trailing stream content')
    with out.open('xb') as f:
        f.write(core)
    if out.stat().st_size != SIZE or sha(out.read_bytes()) != EXPECTED:
        raise ValueError('Saved image mismatch')
    with tail_path.open('xb') as f:
        f.write(tail)
    result = {
        'completed': True,
        'read_only': True,
        'partition_write': False,
        'image': 'original/recovery.img',
        'bytes': SIZE,
        'sha256': EXPECTED,
        'partition_sha_before_equals_after': True,
        'seven_protected_sha_match': True,
        'raw_stream_retained': 'original/recovery.img.partial',
        'raw_stream_bytes': len(raw),
        'raw_stream_sha256': sha(raw),
        'diagnostic_suffix_bytes': len(tail),
        'diagnostic_suffix_sha256': sha(tail),
        'initial_strict_receipt_retained': 'recovery-backup-v1.json',
        'fresh_after_receipt': 'recovery-fresh-after-v2.json',
        'diagnosis': 'Legacy exec-out merged dd stderr after the complete binary partition; the original size guard correctly rejected the unfiltered stream.',
        'files_sha256': {p.name: sha(p.read_bytes()) for p in (HERE / 'recovery-backup-v1.json', HERE / 'recovery-fresh-after-v2.json', Path(__file__), HERE / 'finalize-recovery-backup-v2.ps1')},
    }
    with report.open('x') as f:
        f.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('completed', 'bytes', 'sha256', 'diagnostic_suffix_bytes')}))


if __name__ == '__main__':
    main()
