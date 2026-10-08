#!/usr/bin/env python3
"""Use two recollected chunks; never infer missing UART bytes."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PRIVATE = ROOT / 'outputs/rk3568-pid1-20261005/private'
EXPECTED = '93dfe8b5bb3dc943b2734a07aaca245c2a0ad503890c5256bc6da22f1879c2a0'
NAMES = ['audio-v4-live-fdt-chunks-20261006-v1.raw.txt',
         'audio-v4-live-fdt-repair-20261006-v2.raw.txt']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'extract'])
    args = parser.parse_args()
    if args.action == 'prepare':
        steps = [{'command': 'sha256sum /sys/firmware/fdt', 'wait': 1,
                  'expect': EXPECTED + '  /sys/firmware/fdt'}]
        for index in [91, 112]:
            for part in range(4):
                marker = 'AUDIO_V4_FDT_REPAIR_CHUNK_' + f'{index:04d}' + '_PART_' + str(part)
                command = ('echo ' + marker + ' && dd if=/sys/firmware/fdt bs=256 skip=' + str(index * 4 + part) +
                           ' count=1 2>/dev/null | hexdump -v -e \'1/1 "%02x"\'')
                steps.append({'command': command, 'wait': 0.5})
        steps.append({'command': 'sha256sum /sys/firmware/fdt', 'wait': 1,
                      'expect': EXPECTED + '  /sys/firmware/fdt'})
        with (HERE / 'build/board-audio-v4/live-fdt-repair-v2.json').open('xb') as stream:
            stream.write((json.dumps(steps, indent=2) + '\n').encode())
        print('TWO_FAILED_CHUNKS_PREPARED_AS_EIGHT_FRESH_256_BYTE_READS')
        return
    raw = [(PRIVATE / name).read_bytes() for name in NAMES]
    texts = [data.decode('ascii').replace('\r', '') for data in raw]
    for text in texts:
        assert len(re.findall('^' + EXPECTED + r'  /sys/firmware/fdt$', text, re.M)) == 2
    chunks = []
    for index in range(165):
        if index in [91, 112]:
            parts = []
            for part in range(4):
                marker = 'AUDIO_V4_FDT_REPAIR_CHUNK_' + f'{index:04d}' + '_PART_' + str(part)
                matches = re.findall('^' + marker + r'\n([0-9a-f]+)pid1-rescue#', texts[1], re.M)
                assert len(matches) == 1 and len(matches[0]) == 512, (index, part)
                parts.append(bytes.fromhex(matches[0]))
            chunks.append(b''.join(parts))
        else:
            matches = re.findall('^AUDIO_V4_FDT_CHUNK_' + f'{index:04d}' + r'\n([0-9a-f]+)pid1-rescue#', texts[0], re.M)
            expected = 2048 if index < 164 else 256
            assert len(matches) == 1 and len(matches[0]) == expected, index
            chunks.append(bytes.fromhex(matches[0]))
    data = b''.join(chunks)
    assert len(data) == 168064 and sha(data) == EXPECTED
    assert int.from_bytes(data[4:8], 'big') == len(data)
    output = HERE / 'build/root-live-fdt-v4-audit'
    output.mkdir(exist_ok=False)
    (output / 'live.dtb').write_bytes(data)
    record = {'live_dtb_bytes': len(data), 'live_dtb_sha256': EXPECTED, 'whole_chunks': 165,
              'rejected_chunks': {'91': '1885 instead of 2048 hex', '112': '1954 instead of 2048 hex'},
              'recollected_chunks': [91, 112], 'recollected_parts': 8, 'recollected_block_size': 256,
              'source_evidence': {name: {'bytes': len(blob), 'sha256': sha(blob)} for name, blob in zip(NAMES, raw)},
              'tool_sha256': sha(Path(__file__).read_bytes()), 'no_missing_hex_inferred_or_padded': True,
              'full_semantic_review_pending': True}
    (output / 'extraction.json').write_bytes((json.dumps(record, indent=2) + '\n').encode())
    print(json.dumps(record))


if __name__ == '__main__':
    main()
