#!/usr/bin/env python3
"""Verify the 256-byte transfer rejects incomplete evidence before writing."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('small', HERE / 'live-fdt-transfer-256.py')
small = importlib.util.module_from_spec(spec)
spec.loader.exec_module(small)
transfer = small.transfer
blob = (HERE.parent / 'rk3568-motor-alignment-20261004/uart.dtb').read_bytes()
sha = hashlib.sha256(blob).hexdigest()
meta = f'{transfer.PREFIX}_META_BEGIN\r\n{len(blob)}\r\n{sha}  {transfer.REMOTE}\r\n{transfer.PREFIX}_META_END\r\n'
parts = []
for offset in range(0, len(blob), transfer.CHUNK):
    label = f'{transfer.PREFIX}_{offset:08x}'
    parts.append(f'{label}_BEGIN\r\n{blob[offset:offset + transfer.CHUNK].hex()}\r\n{label}_END\r\n')
final = f'{transfer.PREFIX}_FINAL_BEGIN\r\n{sha}  {transfer.REMOTE}\r\n{transfer.PREFIX}_FINAL_END\r\n'
raw = ''.join(parts) + final
checks = []
with tempfile.TemporaryDirectory(prefix='bootm-fdt-transfer-256-') as directory:
    base = Path(directory)
    metadata = base / 'meta.raw.txt'
    metadata.write_text(meta)
    read_raw = base / 'read.raw.txt'
    read_raw.write_text(raw)
    output, receipt = base / 'fdt.dtb', base / 'receipt.json'
    transfer.audit(metadata, read_raw, output, receipt)
    assert output.read_bytes() == blob
    assert json.loads(receipt.read_text())['chunk_bytes'] == 256
    checks.append('Complete 256-byte transfer has exact original bytes')
    first = blob[:transfer.CHUNK].hex()
    bad_cases = [
        ('Lost hex digit', raw.replace(first, first[1:], 1)),
        ('Repeated chunk', parts[0] + raw),
        ('Missing chunk', raw[len(parts[0]):]),
        ('Foreign output', raw.replace('_BEGIN\r\n', '_BEGIN\r\n[ 1.000] unexpected\r\n', 1)),
        ('Changed final SHA', raw.replace(final, final.replace(sha, '0' * 64))),
        ('Lost end marker', raw.replace(transfer.PREFIX + '_00000000_END', 'LOST_END', 1)),
    ]
    for index, (name, bad) in enumerate(bad_cases):
        read_raw.write_text(bad)
        try:
            transfer.audit(metadata, read_raw, base / f'bad-{index}.dtb', base / f'bad-{index}.json')
        except ValueError:
            assert not (base / f'bad-{index}.dtb').exists()
            checks.append(name + ' rejected before output')
        else:
            raise AssertionError(name)
print(json.dumps({'checks_passed': len(checks), 'checks': checks, 'board_tested': False}, indent=2))
