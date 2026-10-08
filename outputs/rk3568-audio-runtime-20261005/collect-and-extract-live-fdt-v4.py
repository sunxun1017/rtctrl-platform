#!/usr/bin/env python3
"""Prepare bounded UART reads or join exact captures against fresh board SHA."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PRIVATE = ROOT / 'outputs/rk3568-pid1-20261005/private'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'extract'])
    parser.add_argument('--bytes', type=int, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--raw-name', default='audio-v4-live-fdt-chunks-20261006-v1.raw.txt')
    args = parser.parse_args()
    assert 40 <= args.bytes <= 262144 and re.fullmatch('[0-9a-f]{64}', args.sha256)
    assert Path(args.raw_name).name == args.raw_name
    block_size = 1024
    count = (args.bytes + block_size - 1) // block_size
    if args.action == 'prepare':
        steps = [{'command': 'stat -c %s /sys/firmware/fdt', 'wait': 1,
                  'expect': '(?m)^' + str(args.bytes) + r'\r?$'},
                 {'command': 'sha256sum /sys/firmware/fdt', 'wait': 1,
                  'expect': args.sha256 + '  /sys/firmware/fdt'}]
        for index in range(count):
            marker = 'AUDIO_V4_FDT_CHUNK_' + f'{index:04d}'
            command = ('echo ' + marker + ' && dd if=/sys/firmware/fdt bs=1024 skip=' + str(index) +
                       ' count=1 2>/dev/null | hexdump -v -e \'1/1 "%02x"\'')
            steps.append({'command': command, 'wait': 0.3})
        steps.append({'command': 'sha256sum /sys/firmware/fdt', 'wait': 1,
                      'expect': args.sha256 + '  /sys/firmware/fdt'})
        path = HERE / 'build/board-audio-v4/live-fdt-chunks-v1.json'
        write(path, (json.dumps(steps, indent=2) + '\n').encode())
        print(json.dumps({'chunks': count, 'block_size': block_size, 'board_bytes': args.bytes,
                          'board_sha256': args.sha256, 'collection_performed': False}))
    else:
        raw = (PRIVATE / args.raw_name).read_bytes()
        text = raw.decode('ascii').replace('\r', '')
        assert len(re.findall('^' + args.sha256 + r'  /sys/firmware/fdt$', text, re.M)) == 2
        chunks = []
        for index in range(count):
            marker = 'AUDIO_V4_FDT_CHUNK_' + f'{index:04d}'
            captured = re.findall('^' + marker + r'\n([0-9a-f]+)pid1-rescue#', text, re.M)
            expected = 2 * min(block_size, args.bytes - index * block_size)
            if len(captured) != 1 or len(captured[0]) != expected:
                raise ValueError('Incomplete chunk ' + str(index) + ': ' + str([len(item) for item in captured]))
            chunks.append(bytes.fromhex(captured[0]))
        data = b''.join(chunks)
        assert len(data) == args.bytes and sha(data) == args.sha256
        assert int.from_bytes(data[4:8], 'big') == args.bytes
        output = HERE / 'build/root-live-fdt-v4-audit'
        output.mkdir(exist_ok=False)
        write(output / 'live.dtb', data)
        record = {'live_dtb_bytes': args.bytes, 'live_dtb_sha256': args.sha256,
                  'chunks': count, 'block_size': block_size,
                  'source_evidence': {args.raw_name: {'bytes': len(raw), 'sha256': sha(raw)}},
                  'tool_sha256': sha(Path(__file__).read_bytes()),
                  'no_missing_hex_inferred_or_padded': True, 'full_semantic_review_pending': True}
        write(output / 'extraction.json', (json.dumps(record, indent=2) + '\n').encode())
        print(json.dumps(record))


if __name__ == '__main__':
    main()
