#!/usr/bin/env python3
"""Prepare an independent pristine kernel/config; no patching or board I/O."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ORIGINAL = ROOT / 'third_party/linux-rk3588'
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v2'
BUILD = ROOT / '.deps/kernel/aiot-3568pq-audio-v2'
OUT = HERE / 'build/source-preparation-v2'
COMMIT = '9f9e9d18574d0914c0d192a90c3babfe1fd63c95'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


assert git(ORIGINAL, 'rev-parse', 'HEAD') == COMMIT
assert not git(ORIGINAL, 'status', '--porcelain')
assert not SOURCE.exists() and not SOURCE.is_symlink()
assert not BUILD.exists() and not BUILD.is_symlink()
assert shutil.disk_usage(SOURCE.parent).free > 8 * 1024**3
OUT.mkdir(exist_ok=False)
with (OUT / 'clone.txt').open('w') as stream:
    cloned = subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(ORIGINAL), str(SOURCE)], stdout=stream, stderr=subprocess.STDOUT)
assert cloned.returncode == 0
with (OUT / 'checkout.txt').open('w') as stream:
    checked = subprocess.run(['git', '-C', str(SOURCE), 'checkout', '--detach', COMMIT], stdout=stream, stderr=subprocess.STDOUT)
assert checked.returncode == 0 and git(SOURCE, 'rev-parse', 'HEAD') == COMMIT
assert not git(SOURCE, 'status', '--porcelain')
BUILD.mkdir()
old_config = ROOT / '.deps/kernel/aiot-3568pq-audio-v1/.config'
assert sha(old_config) == '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'
shutil.copyfile(old_config, BUILD / '.config')
assert not git(ORIGINAL, 'status', '--porcelain') and git(ORIGINAL, 'rev-parse', 'HEAD') == COMMIT
receipt = {'completed': True, 'source_commit': COMMIT, 'config_sha256': sha(BUILD / '.config'),
           'source': SOURCE.relative_to(ROOT).as_posix(), 'build': BUILD.relative_to(ROOT).as_posix(),
           'original_clean': True, 'patches_applied': False, 'Image_built': False,
           'battery_algorithm_enabled': False, 'hardware_operated': False, 'builder_sha256': sha(Path(__file__))}
(OUT / 'result.json').write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
print('AUDIO_V2_PRISTINE_SOURCE_AND_UNCHANGED_CONFIG_PREPARED', flush=True)
