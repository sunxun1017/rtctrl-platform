#!/usr/bin/env python3
"""Check complete UART transfer and reject loss, duplication and contamination."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('transfer', HERE / 'live-fdt-transfer.py')
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)
workspace = HERE.parent.parent
blob = (workspace / 'outputs/rk3568-motor-alignment-20261004/uart.dtb').read_bytes()
sha = hashlib.sha256(blob).hexdigest()
meta = f'{transfer.PREFIX}_META_BEGIN\r\n{len(blob)}\r\n{sha}  {transfer.REMOTE}\r\n{transfer.PREFIX}_META_END\r\n'
parts = []
for offset in range(0, len(blob), transfer.CHUNK):
    label = f'{transfer.PREFIX}_{offset:08x}'
    parts.append(f'{label}_BEGIN\r\n{blob[offset:offset + transfer.CHUNK].hex()}\r\n{label}_END\r\n')
final = f'{transfer.PREFIX}_FINAL_BEGIN\r\n{sha}  {transfer.REMOTE}\r\n{transfer.PREFIX}_FINAL_END\r\n'
raw = ''.join(parts) + final
checks = []
with tempfile.TemporaryDirectory(prefix='bootm-fdt-transfer-') as directory:
    base = Path(directory)
    metadata = base / 'meta.raw.txt'
    metadata.write_text(meta)
    read_raw = base / 'read.raw.txt'
    read_raw.write_text(raw)
    output, receipt = base / 'fdt.dtb', base / 'receipt.json'
    transfer.audit(metadata, read_raw, output, receipt)
    assert output.read_bytes() == blob
    checks.append('Complete transfer has exact original bytes')
    changed = [
        ('One lost hex digit', raw.replace(blob[:1024].hex(), blob[:1024].hex()[1:], 1)),
        ('Repeated chunk', parts[0] + raw),
        ('Missing chunk', raw[len(parts[0]):]),
        ('Foreign nonempty output', raw.replace('_BEGIN\r\n', '_BEGIN\r\n[ 1.000] unexpected log\r\n', 1)),
        ('Changed final checksum', raw.replace(final, final.replace(sha, '0' * 64))),
        ('Lost end marker', raw.replace(transfer.PREFIX + '_00000000_END', 'LOST_END', 1)),
    ]
    for index, (name, bad) in enumerate(changed):
        read_raw.write_text(bad)
        try:
            transfer.audit(metadata, read_raw, base / f'bad-{index}.dtb', base / f'bad-{index}.json')
        except ValueError:
            assert not (base / f'bad-{index}.dtb').exists()
            checks.append(name + ' rejected before creating output')
        else:
            raise AssertionError(name)
print(json.dumps({'checks_passed': len(checks), 'checks': checks, 'board_tested': False}, indent=2))
