#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read local DT inputs and report relevant nodes without modifying them."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / 'outputs/rk3568-boot-package-20261005'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), PACKAGE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decode(value):
    data = bytes.fromhex(value)
    if data and data[-1:] == b'\0' and all(byte == 0 or 32 <= byte < 127 for byte in data):
        return data[:-1].decode('ascii').split('\0')
    return value


def main():
    semantic = load('dt-semantics-v2.py')
    paths = {
        'original': PACKAGE / 'build/roundtrip-v1/rsce/arch/arm64/boot/dts/rockchip/rk3568_smdt_3568a_v20.dtb',
        'audio': ROOT / 'outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb',
    }
    for name, path in paths.items():
        data = path.read_bytes()
        tree = semantic.parse(data)
        interesting = [node for node in tree['nodes'] if 'usb' in node or 'combo' in node or 'fe310000' in node or 'vcc5' in node]
        result = {'name': name, 'path': str(path.relative_to(ROOT)), 'bytes': len(data),
                  'sha256': hashlib.sha256(data).hexdigest(), 'nodes': {}}
        for node in interesting:
            result['nodes'][node] = {key.rsplit(':', 1)[1]: decode(value)
                                    for key, value in tree['properties'].items()
                                    if key.rsplit(':', 1)[0] == node}
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
