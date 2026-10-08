#!/usr/bin/env python3
"""Exact CRC/length RAM boot commands for the final networking initramfs."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

root = Path.cwd()
out = root/'outputs/rk3568-source-wifi-20261004'
image = root/'outputs/rk3568-rcu-reset-20261004/Image'
inputs = [(image, 'Image', 0x400000), (out/'wifi.dtb', 'wifi.dtb', 0x3000000),
          (out/'initramfs-v5.cpio.gz', 'initramfs-v5.cpio.gz', 0x4000000)]
metadata, load = {}, []
for path, name, address in inputs:
    data = path.read_bytes()
    crc = zlib.crc32(data)
    metadata[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                      'crc32': f'{crc:08x}', 'load_address': hex(address)}
    load.extend([
        {'command': f'ext4load mmc 0:c {address:x} /rtctrl-source-wifi-20261004/{name}', 'wait': 4, 'expect': f'{len(data)} bytes read'},
        {'command': f'crc32 {address:x} {len(data):x}', 'expect': f'==> {crc:08x}'},
    ])
load.extend([{'command': 'fdt addr 3000000'}, {'command': 'fdt rsvmem print'},
             {'command': 'fdt print /reserved-memory', 'expect': 'no-map'}])
header = image.read_bytes()[:64]
text_offset, span, flags = struct.unpack_from('<QQQ', header, 8)
assert text_offset == 0 and span == 0x21c0000
assert 0x400000 + span < 0x3000000
assert 0x4000000 + inputs[-1][0].stat().st_size < 0x8400000
boot = json.loads((root/'outputs/rk3568-rcu-reset-20261004/boot-ram.json').read_text())
boot[-1]['command'] = f'booti 400000 4000000:{inputs[-1][0].stat().st_size:x} 3000000'
for name, record in [('load-ram.json', load), ('boot-ram.json', boot), ('boot-inputs.json', metadata)]:
    (out/name).write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(metadata, indent=2))
