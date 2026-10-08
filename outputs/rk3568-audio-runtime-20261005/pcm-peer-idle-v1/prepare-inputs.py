#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy locked inputs and byte-exact PCM parameter helpers into the new directory."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parent / 'pcm-config.c'


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Ordinary input required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, data):
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError('Never replace prepared input: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle:
            handle.write(data)


def main():
    if digest(BASE) != 'bf3c513fc98474c55346c77277e347c2bc0e194480c76c1fd6d1d2d9fbb98b2a':
        raise ValueError('Actual pcm-config baseline changed')
    prefix = BASE.read_bytes().split(b'static void print_caps', 1)[0]
    write_once(HERE / 'parameters.h', prefix)
    names = ['outputs/rk3568-audio-runtime-20261005/pcm-config.c',
             'outputs/rk3568-audio-runtime-20261005/test-pcm-config.py',
             'outputs/rk3568-audio-runtime-20261005/build-pcm-config.py',
             'outputs/rk3568-audio-runtime-20261005/build/pcm-production-v1/pcm-config',
             'outputs/rk3568-audio-runtime-20261005/build/pcm-production-v1/manifest.json',
             'third_party/linux-rk3588/include/uapi/sound/asound.h',
             '.deps/kernel/aiot-3568pq-audio-v3/.config',
             'docs/superpowers/specs/2026-10-06-rk3568-pcm-peer-idle-design.md']
    inputs = {name: digest(ROOT / name) for name in names}
    if inputs[names[5]] != '138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447' or \
            inputs[names[6]] != '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912':
        raise ValueError('Locked UAPI/config mismatch')
    for name in names:
        write_once(HERE / 'inputs' / name, (ROOT / name).read_bytes())
    manifest = {'external_inputs_sha256': inputs, 'parameters_header_sha256': digest(HERE / 'parameters.h'),
                'parameters_header_is_exact_pcm_config_prefix': True}
    write_once(HERE / 'input-manifest.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
