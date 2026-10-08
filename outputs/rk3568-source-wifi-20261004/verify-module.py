#!/usr/bin/env python3
"""Require the final module's undefined symbols in the tested vmlinux exports."""
import hashlib
import json
from pathlib import Path
import subprocess

out = Path('outputs/rk3568-source-wifi-20261004')
build = Path('.deps/kernel/aiot-3568pq-rcu-reset')
module = out/'bcmdhd.ko'
exports = {line.split()[1] for line in (build/'vmlinux.symvers').read_text().splitlines()}
undefined = subprocess.check_output(['aarch64-linux-gnu-nm', '-u', str(module)], text=True)
names = [line.split()[-1] for line in undefined.splitlines()]
assert set(names) <= exports, sorted(set(names) - exports)
info = subprocess.check_output(['aarch64-linux-gnu-readelf', '-p', '.modinfo', str(module)], text=True)
expected = '5.10.160-rt89-g9f9e9d18574d-dirty'
assert 'vermagic=' + expected + ' SMP preempt_rt mod_unload aarch64' in info
assert 'import_ns=VFS_internal_I_am_really_a_filesystem_and_am_NOT_a_driver' in info
image = Path('outputs/rk3568-rcu-reset-20261004/Image')
expected_image = 'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457'
assert hashlib.sha256(image.read_bytes()).hexdigest() == expected_image
assert hashlib.sha256((build/'arch/arm64/boot/Image').read_bytes()).hexdigest() == expected_image
assert (build/'.config').read_bytes() == Path('outputs/rk3568-rcu-reset-20261004/kernel.config').read_bytes()
result = {'module_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
          'undefined_symbols': len(names), 'missing_exports': [], 'vermagic': expected,
          'image_sha256': expected_image, 'same_config': True, 'board_loaded': False}
(out/'module-check.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
