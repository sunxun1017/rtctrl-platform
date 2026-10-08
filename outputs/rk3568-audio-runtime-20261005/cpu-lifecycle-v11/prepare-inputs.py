#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Snapshot real caller/CPU/ABI inputs; no writes outside the new v11 directory."""
from pathlib import Path
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'outputs/rk3568-i2s-lifecycle-20261005'
KERNEL = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v1'
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
CPU_SHA = 'cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = HERE / 'inputs'
    out.mkdir(exist_ok=False)
    selected = [OLD / 'driver-source-v10' / SOURCE,
                OLD / 'driver-source-v10/manifest.json',
                OLD / 'driver-source-v10/i2s-lifecycle-pm.patch',
                OLD / 'sealed-v3/manifest.json', OLD / 'source_utils.py',
                OLD / 'test-params-shim.h', OLD / 'test-params-main.c',
                KERNEL / SOURCE,
                KERNEL / 'sound/soc/generic/simple-card-utils.c',
                KERNEL / 'sound/soc/soc-pcm.c', KERNEL / 'sound/soc/soc-dai.c',
                KERNEL / 'sound/soc/codecs/rk817_codec.c',
                KERNEL / 'include/sound/simple_card_utils.h',
                KERNEL / 'include/sound/pcm.h', KERNEL / 'include/sound/pcm_params.h',
                KERNEL / 'include/sound/soc-dai.h', KERNEL / 'include/sound/dmaengine_pcm.h',
                KERNEL / 'include/uapi/sound/asound.h', KERNEL / 'include/uapi/sound/asoc.h',
                KERNEL / 'sound/soc/rockchip/rockchip_i2s_tdm.h',
                KERNEL / 'sound/soc/rockchip/rockchip_dlp.h']
    for path in [OLD / 'driver-source-v10' / SOURCE, KERNEL / SOURCE]:
        if sha(path) != CPU_SHA:
            raise ValueError('Need byte-exact accepted v10 CPU source')
    protected = [OLD / 'driver-source-v10' / SOURCE,
                 ROOT / 'third_party/linux-rk3588' / SOURCE,
                 KERNEL / SOURCE,
                 ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches/0012-i2s-lifecycle.patch',
                 HERE.parent / 'build/integration-v1/Image',
                 HERE.parent / 'build/integration-v1/manifest.json',
                 ROOT / 'outputs/rk3568-audio-package-20261005/build/ram-audio-v2/boot-padded.img',
                 ROOT / 'outputs/rk3568-pid1-20261005/pid1.c']
    for name in ['.config', 'Module.symvers', 'vmlinux.symvers', 'include/generated/utsrelease.h']:
        protected.append(ROOT / '.deps/kernel/aiot-3568pq-audio-v1' / name)
    protected_sha = {}
    for path in protected:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing/nonregular protected input: ' + str(path))
        protected_sha[path.relative_to(ROOT).as_posix()] = sha(path)
    original = ROOT / 'third_party/linux-rk3588'
    commit = subprocess.check_output(['git', '-C', str(original), 'rev-parse', 'HEAD'], text=True).strip()
    status = subprocess.check_output(['git', '-C', str(original), 'status', '--porcelain'], text=True)
    if commit != '9f9e9d18574d0914c0d192a90c3babfe1fd63c95' or status:
        raise ValueError('Original kernel identity or cleanliness changed')
    copies = {}
    for path in selected:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing/nonregular input: ' + str(path))
        relative = path.relative_to(ROOT)
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        copies[relative.as_posix()] = sha(target)
    (HERE / 'source_utils.py').write_bytes((OLD / 'source_utils.py').read_bytes())
    (HERE / 'input-manifest.json').write_text(json.dumps({
        'board_accessed': False, 'cpu_v10_sha256': CPU_SHA,
        'inputs_sha256': copies, 'protected_sha256': protected_sha,
        'original_kernel_commit': commit, 'original_kernel_clean': True,
        'writes_limited_to_new_v11_directory': True
    }, indent=2) + '\n')
    print(json.dumps({'inputs': len(copies), 'protected': len(protected_sha), 'cpu_v10_sha256': CPU_SHA}))


if __name__ == '__main__':
    main()
