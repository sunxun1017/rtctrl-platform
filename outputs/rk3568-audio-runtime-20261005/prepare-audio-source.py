#!/usr/bin/env python3
"""Prepare an independent, clean audio integration checkout and tested config."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ORIGINAL = ROOT / 'third_party/linux-rk3588'
COMMIT = '9f9e9d18574d0914c0d192a90c3babfe1fd63c95'
CONFIG_SHA = '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v1'
BUILD = ROOT / '.deps/kernel/aiot-3568pq-audio-v1'
OUT = HERE / 'build/integration-prepare-v1'


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def lock_original():
    if git(ORIGINAL, 'rev-parse', 'HEAD') != COMMIT or git(ORIGINAL, 'status', '--porcelain'):
        raise ValueError('Original locked source changed')


lock_original()
if any(path.exists() or path.is_symlink() for path in (SOURCE, BUILD, OUT)):
    raise ValueError('Refusing to overwrite integration source/build/evidence')
OUT.mkdir(parents=True)
SOURCE.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(ORIGINAL), str(SOURCE)], check=True)
subprocess.run(['git', '-C', str(SOURCE), 'checkout', '--detach', COMMIT], check=True)
subprocess.run([
    'python3', str(ROOT / 'scripts/prepare-linux-config.py'),
    '--candidate', str(ROOT / 'platforms/rk3568/boards/aiot-3568pq/firstboot-candidate.json'),
    '--source', str(SOURCE), '--output', str(BUILD),
], check=True)
lock_original()
if git(SOURCE, 'status', '--porcelain') or git(SOURCE, 'rev-parse', 'HEAD') != COMMIT:
    raise ValueError('New private source is not clean')
config_sha = hashlib.sha256((BUILD / '.config').read_bytes()).hexdigest()
if config_sha != CONFIG_SHA:
    raise ValueError('New private config differs from tested Image')
result = {
    'source': str(SOURCE), 'build': str(BUILD), 'source_commit': COMMIT,
    'config_sha256': config_sha, 'source_clean': True, 'original_clean': True,
    'patches_applied': False, 'image_built': False, 'deployed': False,
}
(OUT / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
print('AUDIO_INTEGRATION_CLEAN_SOURCE_CONFIG_READY')
