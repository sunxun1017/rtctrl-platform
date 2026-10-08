#!/usr/bin/env python3
"""Plan/read a bounded, checksummed UART FDT copy. No hardware operations."""
import argparse
import hashlib
import json
from pathlib import Path
import re

REMOTE = '/tmp/bootm-live.dtb'
PREFIX = 'BOOTM_LIVE_FDT'
LIMIT = 1024 * 1024
CHUNK = 1024


def exclusive_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def payload(raw, label):
    lines = raw.splitlines()
    begin = [i for i, line in enumerate(lines) if line == label + '_BEGIN']
    end = [i for i, line in enumerate(lines) if line == label + '_END']
    if len(begin) != 1 or len(end) != 1 or begin[0] >= end[0]:
        raise ValueError('Missing, repeated or reordered markers: ' + label)
    return [line for line in lines[begin[0] + 1:end[0]] if line]


def metadata(raw):
    data = payload(raw, PREFIX + '_META')
    if len(data) != 2 or not re.fullmatch(r'[1-9][0-9]*', data[0]):
        raise ValueError('Unexpected metadata payload')
    size = int(data[0])
    match = re.fullmatch(r'([0-9a-f]{64})  ' + re.escape(REMOTE), data[1])
    if not match or not 40 <= size <= LIMIT:
        raise ValueError('Invalid FDT size or checksum metadata')
    return size, match[1]


def plan_meta(destination):
    exclusive_json(destination, [{
        'command': f'test ! -e {REMOTE} && test ! -L {REMOTE} && '
                   f'cp /sys/firmware/fdt {REMOTE} && '
                   f'echo {PREFIX}_META_BEGIN && stat -c "%s" {REMOTE} && '
                   f'sha256sum {REMOTE} && echo {PREFIX}_META_END',
        'wait': 1,
        'expect': rf'(?m)^{PREFIX}_META_END\r?$',
    }])


def plan_read(meta_raw, destination):
    size, sha = metadata(meta_raw.read_text())
    steps = []
    for offset in range(0, size, CHUNK):
        count = min(CHUNK, size - offset)
        label = f'{PREFIX}_{offset:08x}'
        steps.append({
            'command': f'echo {label}_BEGIN && hexdump -v -s {offset} '
                       f'-n {count} -e \'1/1 "%02x"\' {REMOTE} && '
                       f'echo && echo {label}_END',
            'wait': 1,
            'expect': rf'(?m)^{label}_END\r?$',
        })
    steps.append({
        'command': f'echo {PREFIX}_FINAL_BEGIN && sha256sum {REMOTE} && '
                   f'echo {PREFIX}_FINAL_END',
        'wait': 1,
        'expect': rf'(?m)^{PREFIX}_FINAL_END\r?$',
    })
    exclusive_json(destination, steps)
    return {'bytes': size, 'sha256': sha, 'chunks': len(steps) - 1}


def audit(meta_raw, read_raw, output, receipt):
    size, sha = metadata(meta_raw.read_text())
    raw = read_raw.read_text()
    result = bytearray()
    for offset in range(0, size, CHUNK):
        count = min(CHUNK, size - offset)
        label = f'{PREFIX}_{offset:08x}'
        data = payload(raw, label)
        if len(data) != 1 or not re.fullmatch('[0-9a-f]{' + str(count * 2) + '}', data[0]):
            raise ValueError('Incomplete or contaminated chunk: ' + label)
        result.extend(bytes.fromhex(data[0]))
    if payload(raw, PREFIX + '_FINAL') != [sha + '  ' + REMOTE]:
        raise ValueError('Final board checksum differs')
    if len(result) != size or hashlib.sha256(result).hexdigest() != sha:
        raise ValueError('Reconstructed FDT differs from board copy')
    if result[:4] != bytes.fromhex('d00dfeed') or int.from_bytes(result[4:8], 'big') != size:
        raise ValueError('Reconstructed FDT header differs')
    if output.exists() or receipt.exists():
        raise ValueError('Refusing to overwrite evidence')
    with output.open('xb') as stream:
        stream.write(result)
    exclusive_json(receipt, {
        'bytes': size, 'sha256': sha, 'chunks': (size + CHUNK - 1) // CHUNK,
        'chunk_bytes': CHUNK,
        'metadata_raw_sha256': hashlib.sha256(meta_raw.read_bytes()).hexdigest(),
        'read_raw_sha256': hashlib.sha256(read_raw.read_bytes()).hexdigest(),
        'board_sha_matches_reconstruction': True,
        'semantic_audit_completed': False,
    })
    return {'bytes': size, 'sha256': sha, 'transfer_verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    meta = sub.add_parser('plan-meta')
    meta.add_argument('destination', type=Path)
    read = sub.add_parser('plan-read')
    read.add_argument('metadata_raw', type=Path)
    read.add_argument('destination', type=Path)
    check = sub.add_parser('audit')
    check.add_argument('metadata_raw', type=Path)
    check.add_argument('read_raw', type=Path)
    check.add_argument('output', type=Path)
    check.add_argument('receipt', type=Path)
    args = parser.parse_args()
    if args.operation == 'plan-meta':
        plan_meta(args.destination)
    elif args.operation == 'plan-read':
        print(json.dumps(plan_read(args.metadata_raw, args.destination)))
    else:
        print(json.dumps(audit(args.metadata_raw, args.read_raw, args.output, args.receipt)))


if __name__ == '__main__':
    main()
