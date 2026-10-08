#!/usr/bin/env python3
"""LF-only native3 RAM staging from the verified v2 ordinary cache files."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'build/ram-aux-v3'
OUT.mkdir(exist_ok=False)
def sha(data):
    return hashlib.sha256(data).hexdigest()
manifest = json.loads((HERE / 'build/board-audio-v2/input-manifest.json').read_text())
names = ['snd-soc-rk817.ko', 'alsa-inspect', 'pcm-transfer', 'audio-session-guard']
files = [x for x in manifest['files'] if x['name'] in names]
assert len(files) == 4
for x in files:
    assert sha((ROOT / x['source']).read_bytes()) == x['sha256']
remote = '/.backing-cache/rtctrl-audio-bootm-20261005-v2'
script = '''#!/bin/sh
set -eu
test "$(uname -r)" = 5.10.160-rt89-g9f9e9d18574d-dirty
test "$(readlink -f /proc/1/exe)" = /bin/pid1
test "$(sha256sum /proc/1/exe)" = '249cc1cfd87cbddc8618e81e6b8fd742526de78fd964d4a4b3b59b8a7d76368b  /proc/1/exe'
test -z "$(cat /proc/modules)"
test ! -e /tmp/audio
test ! -L /tmp/audio
test ! -e /dev/McuCom
'''
for x in files:
    path = remote + '/' + x['name']
    script += 'test "$(sha256sum ' + path + ')" = \'' + x['sha256'] + '  ' + path + "'\n"
script += 'mkdir -m 700 /tmp/audio\n'
script += 'cp ' + ' '.join(remote + '/' + name for name in names) + ' /tmp/audio/\n'
for x in files:
    path = '/tmp/audio/' + x['name']
    script += 'test "$(sha256sum ' + path + ')" = \'' + x['sha256'] + '  ' + path + "'\n"
script += 'chmod 500 /tmp/audio/alsa-inspect /tmp/audio/pcm-transfer /tmp/audio/audio-session-guard\n'
script += 'echo AUDIO_RAM_AUX_V3_VERIFIED_NO_MODULE_OR_START\n'
data = script.encode('ascii')
assert b'\r' not in data
(OUT / 'stage.sh').write_bytes(data)
steps = [{'command': 'test ! -e /tmp/audio-stage-v3.sh && test ! -L /tmp/audio-stage-v3.sh && echo AUDIO_STAGE_V3_ABSENT',
          'wait': 1, 'expect': r'(?m)^AUDIO_STAGE_V3_ABSENT\r?$'}]
for offset in range(0, len(data), 96):
    encoded = ''.join('\\0' + f'{b:03o}' for b in data[offset:offset + 96])
    steps.append({'command': "printf '%b' '" + encoded + "' " + ('>' if offset == 0 else '>>') + ' /tmp/audio-stage-v3.sh', 'wait': 0.05})
steps.append({'command': 'test "$(sha256sum /tmp/audio-stage-v3.sh)" = \'' + sha(data) + "  /tmp/audio-stage-v3.sh' && sh /tmp/audio-stage-v3.sh",
              'wait': 5, 'expect': r'(?m)^AUDIO_RAM_AUX_V3_VERIFIED_NO_MODULE_OR_START\r?$'})
(OUT / 'copy.json').write_bytes((json.dumps(steps, indent=2) + '\n').encode())
(OUT / 'manifest.json').write_bytes((json.dumps({'script_sha256': sha(data), 'files': files,
    'lf_only': True, 'cache_mount': '/.backing-cache', 'start_allowed': False,
    'guard_v2_not_usable_for_actual_dmac_name': True}, indent=2) + '\n').encode())
print(json.dumps({'bytes': len(data), 'sha256': sha(data), 'start_allowed': False}))
