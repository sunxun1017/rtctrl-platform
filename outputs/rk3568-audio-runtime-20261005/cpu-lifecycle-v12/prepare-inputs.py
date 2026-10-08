#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Snapshot v11 and actual PM/ASoC contracts; writes only fresh v12 inputs."""
from pathlib import Path
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = HERE.parent / 'cpu-lifecycle-v11'
KERNEL = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v2'
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
CPU_SHA = '87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = HERE / 'inputs'
    out.mkdir(exist_ok=False)
    names = [SOURCE, 'sound/soc/soc-core.c', 'sound/soc/soc-component.c',
             'sound/soc/soc-pcm.c', 'drivers/base/power/runtime.c',
             'drivers/base/power/sysfs.c', 'include/linux/pm_runtime.h']
    selected = [KERNEL / name for name in names]
    selected += [PRIOR / 'source' / SOURCE, PRIOR / 'source/manifest.json',
                 PRIOR / 'input-manifest.json', PRIOR / 'receipt.json',
                 PRIOR / 'frozen-output-manifest.json', PRIOR / 'source_utils.py',
                 PRIOR / 'test-sysclk-shutdown.py', PRIOR / 'test-sysclk-main.c',
                 PRIOR / 'simple-model-glue.h', PRIOR / 'build-object.py']
    # Reuse byte-exact caller/header fixtures from the accepted v11 snapshot.
    selected += [path for path in (PRIOR / 'inputs').rglob('*') if path.is_file()]
    for path in [KERNEL / SOURCE, PRIOR / 'source' / SOURCE]:
        if sha(path) != CPU_SHA:
            raise ValueError('Need actual accepted v11 source')
    old_inventory = json.loads((PRIOR / 'frozen-output-manifest.json').read_text())['files_sha256']
    for name, digest in old_inventory.items():
        if sha(PRIOR / name) != digest:
            raise ValueError('Prior v11 freeze changed: ' + name)
    copies = {}
    for path in selected:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Nonordinary input')
        relative = path.relative_to(ROOT)
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copies[relative.as_posix()] = sha(target)
    protected_paths = [KERNEL / SOURCE, ROOT / 'third_party/linux-rk3588' / SOURCE,
                       ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches/0012-i2s-lifecycle.patch',
                       HERE.parent / 'build/integration-v2/Image',
                       HERE.parent / 'build/integration-v2/manifest.json',
                       ROOT / 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/boot-padded.img']
    for name in ['.config', 'Module.symvers', 'vmlinux.symvers', 'include/generated/utsrelease.h']:
        protected_paths.append(ROOT / '.deps/kernel/aiot-3568pq-audio-v2' / name)
    protected = {path.relative_to(ROOT).as_posix(): sha(path) for path in protected_paths}
    (HERE / 'source_utils.py').write_bytes((PRIOR / 'source_utils.py').read_bytes())
    # The unchanged v11 runner is redirected to snapshots by our wrapper.
    (HERE / 'input-manifest.json').write_text(json.dumps({
        'version': 12, 'cpu_v11_sha256': CPU_SHA, 'inputs_sha256': copies,
        'protected_sha256': protected,
        'v11_inventory_sha256': sha(PRIOR / 'frozen-output-manifest.json'),
        'v11_SHA256SUMS_sha256': sha(PRIOR / 'SHA256SUMS'),
        'v11_files_sha256': old_inventory, 'board_accessed': False,
        'writes_limited_to_new_v12_directory': True
    }, indent=2) + '\n')
    print(json.dumps({'copied': len(copies), 'protected': len(protected),
                      'prior_v11_frozen_files_verified': len(old_inventory)}))


if __name__ == '__main__':
    main()
