#!/usr/bin/env python3
"""Record the strict seven-checksum Android baseline captured over UART."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
private = HERE.parent / 'rk3568-pid1-20261005/private'
raw_path = private / 'android-baseline-after-linux-bootm-v2.raw.txt'
raw = raw_path.read_bytes().decode('ascii').replace('\r\n', '\n')
steps = json.loads((HERE / 'android-baseline-after-v2-serial.json').read_text())
names = ['root', 'kernel', 'android', 'boot_completed', 'boot_sha256', 'uboot_sha256',
         'trust_sha256', 'dtbo_sha256', 'vbmeta_sha256', 'source_rootfs_sha256', 'network_rootfs_sha256']
sections = {}
for name, step in zip(names, steps):
    matches = re.findall(step['expect'], raw)
    if len(matches) != 1:
        raise ValueError('Missing or repeated result: ' + name)
    matched = matches[0]
    if name == 'root':
        matched = re.search(r'(?m)^uid=0\(root\)[^\n]*', raw)[0]
    sections[name] = {'command': step['command'], 'output': matched, 'exit_code': None,
                      'verification': 'Exact UART response; shell exit not independently observed'}
levels = re.findall(r'(?m)^\s*level: (\d+)\s*$', raw)
if len(levels) != 1 or not 0 <= int(levels[0]) <= 100:
    raise ValueError('Missing or repeated battery level')
sections['battery'] = {'command': 'su 0 dumpsys battery', 'output': 'level: ' + levels[0],
                       'exit_code': None, 'verification': 'Fresh dumpsys field in raw evidence'}
result = {'phase': 'after-linux-bootm-v2-and-before-next-ram-trial', 'sections': sections,
          'raw_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
          'transport': 'UART', 'protected_sha256_count': 7, 'success': True}
with (private / 'android-after-linux-bootm-v2-serial.json').open('x') as stream:
    json.dump(result, stream, indent=2)
    stream.write('\n')
print(json.dumps({'android': 11, 'kernel': sections['kernel']['output'],
                  'protected_sha256_count': 7, 'battery_percent': int(levels[0])}))
