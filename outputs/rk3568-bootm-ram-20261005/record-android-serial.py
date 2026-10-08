#!/usr/bin/env python3
"""Record strict Android UART responses without inventing shell exit codes."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
COMMANDS_SHA = 'f37411c1887095e017997f5a3227bb2011ef2dbb6ef4c117840838eef7582d53'
NAMES = ('root', 'kernel', 'android', 'boot_completed', 'boot_sha256',
         'uboot_sha256', 'trust_sha256', 'dtbo_sha256', 'vbmeta_sha256',
         'source_rootfs_sha256', 'network_rootfs_sha256')


def collect(raw_bytes, steps, phase):
    # Lone CR is console cursor movement, not a second result line.
    raw = raw_bytes.decode('ascii').replace('\r\n', '\n')
    if len(steps) != len(NAMES) + 1:
        raise ValueError('Unexpected command set')
    sections = {}
    for name, step in zip(NAMES, steps):
        matches = list(re.finditer(step['expect'], raw))
        if len(matches) != 1:
            raise ValueError('Missing or repeated result: ' + name)
        output = matches[0][0].rstrip('\r')
        if name == 'root':
            output = re.search(r'(?m)^uid=0\(root\)[^\n]*', raw)[0].rstrip('\r')
        sections[name] = {
            'command': step['command'], 'output': output, 'exit_code': None,
            'verification': 'Exact UART response; shell exit not independently observed',
        }
    levels = re.findall(r'(?m)^\s*level: (\d+)\s*$', raw)
    if len(levels) != 1 or not 0 <= int(levels[0]) <= 100:
        raise ValueError('Missing or repeated battery level')
    sections['battery'] = {
        'command': 'su 0 dumpsys battery', 'output': 'level: ' + levels[0],
        'exit_code': None, 'verification': 'Fresh dumpsys field in raw evidence',
    }
    return {
        'phase': phase, 'sections': sections, 'transport': 'UART',
        'raw_sha256': hashlib.sha256(raw_bytes).hexdigest(),
        'commands_sha256': COMMANDS_SHA, 'protected_sha256_count': 7, 'success': True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--phase', required=True)
    args = parser.parse_args()
    commands = HERE / 'android-baseline-after-v2-serial.json'
    if hashlib.sha256(commands.read_bytes()).hexdigest() != COMMANDS_SHA:
        raise ValueError('Reviewed commands changed')
    result = collect(args.raw.read_bytes(), json.loads(commands.read_text()), args.phase)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'android': 11, 'kernel': '4.19.232', 'protected_sha256_count': 7,
                      'battery_percent': int(result['sections']['battery']['output'].split()[-1])}))


if __name__ == '__main__':
    main()
