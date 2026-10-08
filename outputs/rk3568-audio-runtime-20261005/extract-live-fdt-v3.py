#!/usr/bin/env python3
"""Join only complete captured chunks; validate against the fresh board SHA."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PRIVATE = ROOT / 'outputs/rk3568-pid1-20261005/private'
OUT = HERE / 'build/root-live-fdt-v3-audit'
names = ['audio-v3-live-fdt-chunks-20261006-v2.raw.txt',
         'audio-v3-live-fdt-chunk-22-20261006-v3.raw.txt']
evidence = {}
texts = []
for name in names:
    data = (PRIVATE / name).read_bytes()
    evidence[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    texts.append(data.decode('ascii').replace('\r', ''))

blocks = []
for index in range(42):
    if index == 22:
        pieces = []
        for part in range(8):
            matches = re.findall(r'^AUDIO_V3_FDT_CHUNK_22_PART_' + str(part) +
                                 r'\n([0-9a-f]+)pid1-rescue#', texts[1], re.M)
            assert len(matches) == 1 and len(matches[0]) == 1024, part
            pieces.append(bytes.fromhex(matches[0]))
        blocks.append(b''.join(pieces))
    else:
        matches = re.findall(r'^AUDIO_V3_FDT_CHUNK_' + f'{index:02d}' +
                             r'\n([0-9a-f]+)pid1-rescue#', texts[0], re.M)
        expected = 8192 if index < 41 else 256
        assert len(matches) == 1 and len(matches[0]) == expected, index
        blocks.append(bytes.fromhex(matches[0]))
data = b''.join(blocks)
expected_sha = 'c1cf7fd3ea52dc33171d6631f46d587d68fa180737c16c8d22fd0a69a0a3120a'
assert len(data) == 168064
assert hashlib.sha256(data).hexdigest() == expected_sha
assert int.from_bytes(data[4:8], 'big') == len(data)
for text in texts:
    assert re.search('^' + expected_sha + r'  /sys/firmware/fdt$', text, re.M)
assert not OUT.exists()
OUT.mkdir()
(OUT / 'live.dtb').write_bytes(data)
record = {
    'live_dtb_bytes': len(data), 'live_dtb_sha256': expected_sha,
    'chunks': 42, 'chunk_22_recollected_parts': 8,
    'offsets': {'whole_chunks_bs': 4096, 'recollected_bs': 512, 'recollected_skip': list(range(176, 184))},
    'source_evidence': evidence,
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'no_missing_hex_inferred_or_padded': True,
    'full_semantic_review_pending': True,
}
(OUT / 'extraction.json').write_bytes((json.dumps(record, indent=2) + '\n').encode())
print(json.dumps(record))
