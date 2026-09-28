import base64
import hashlib
import json
from pathlib import Path
import re
import struct

p = Path(__file__).resolve().parent
b = (p / 'boot-header.bin').read_bytes()
assert len(b) == 4096 and b[:8] == b'ANDROID!'
digest = hashlib.sha256(b).hexdigest()
assert digest in (p / '04-header-hash.output.txt').read_text()
names = ('kernel_size', 'kernel_addr', 'ramdisk_size', 'ramdisk_addr',
         'second_size', 'second_addr', 'tags_addr', 'page_size', 'header_version', 'os_version')
result = dict(zip(names, struct.unpack_from('<10I', b, 8)))
result.update(header_sha256=digest, full_partition_backed_up=False,
              cmdline=(b[64:576] + b[608:1632]).split(b'\0')[0].decode())
result['recovery_dtbo_size'], result['recovery_dtbo_offset'], result['header_size'] = struct.unpack_from('<IQI', b, 1632)
result['dtb_size'], result['dtb_addr'] = struct.unpack_from('<IQ', b, 1648)
(p / 'boot-header.json').write_text(json.dumps(result, indent=2) + '\n')
text = (p / '06-component-headers.output.txt').read_text()
headers = {}
for name in ('uboot', 'trust', 'dtbo', 'vbmeta'):
    # Only actual standalone markers, not echoed terminal command text.
    match = re.search(r'^__HEADER_' + name + r'\s*\n(.*?)(?=^__HEADER_|console:/|\Z)', text, re.M | re.S)
    if match:
        lines = [line for line in match[1].splitlines() if re.fullmatch(r'[A-Za-z0-9+/]{4,}={0,2}', line)]
        raw = base64.b64decode(''.join(lines))
        digest = hashlib.sha256(raw).hexdigest()
        assert len(raw) == 512
        assert digest in (p / '07-component-hashes.output.txt').read_text()
        headers[name] = {'bytes': len(raw), 'prefix_hex': raw[:32].hex(), 'sha256': digest, 'hash_verified': True}
        (p / (name + '-header.bin')).write_bytes(raw)
(p / 'component-headers.json').write_text(json.dumps(headers, indent=2) + '\n')
print(json.dumps(result, indent=2))
