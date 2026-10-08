#!/usr/bin/env python3
"""Bind fresh Image notes and codec to non-START observation commands."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE / 'build/board-audio-v3'
OUT = HERE / 'build/board-audio-v4'


def write(name, steps):
    with (OUT / name).open('xb') as stream:
        stream.write((json.dumps(steps, indent=2) + '\n').encode())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


notes = json.loads((HERE / 'build/live-image-v3-id/identity.json').read_text())
codec_path = HERE / 'build/integrated-codec-v3/manifest.json'
codec = json.loads(codec_path.read_text())
board = json.loads((OUT / 'input-manifest.json').read_text())
assert board['image_sha256'] == notes['image_sha256'] == codec['image_sha256']
assert notes['notes_bytes'] == 60
assert codec['module']['sha256'] == 'd62205da6efae956ceb8b78059dc90fa405dfef82f94bdb7b8f003a6330ecbf7'
assert notes['notes_sha256'] == '59373c55bac7c0b89c2da52f489c32f90d4dac2b0a85f55aafb87163f1d370af'
assert len(codec['abi_inventory']) == 1934
source = (OLD / 'live-image-identity-v2.json').read_text()
source = source.replace('31152f433f71e10fa685762108333ecaa5c4b6eb69613c65ffef7d8765c9682b', notes['notes_sha256'])
source = source.replace('66eae96027cd89c53d2857bc971d23cccb298360', notes['gnu_build_id'])
steps = json.loads(source)
steps.insert(8, {'command': 'stat -c %s /sys/firmware/fdt', 'wait': 1})
write('live-image-identity-v1.json', steps)
source = (OLD / 'codec-observation.json').read_text()
source = source.replace('31152f433f71e10fa685762108333ecaa5c4b6eb69613c65ffef7d8765c9682b', notes['notes_sha256'])
source = source.replace('4a18293a611882876c600dfa429ab22155b1c10f2563921267bc00ffa80ea615', codec['module']['sha256'])
source = source.replace('AUDIO_V3_IMAGE_AND_GUARD_ID_VERIFIED', 'AUDIO_V4_IMAGE_AND_GUARD_ID_VERIFIED')
write('codec-observation.json', json.loads(source))
write('fresh-fdt-before-boot.json', json.loads((OLD / 'fresh-fdt-before-boot.json').read_text()))
write('android-return-identity.json', json.loads((OLD / 'android-return-identity.json').read_text()))
unmount = json.loads((HERE / 'build/live-audio-v4/unmount-audio-debug.json').read_text())
unmount[1]['command'] = unmount[1]['command'].replace('/sys/module/snd_pcm_dmaengine/parameters/rtctrl_quarantined_buffers',
                                                   '/sys/class/sound/dma_quarantine_bytes')
write('unmount-audio-debug.json', unmount)
proof = {'prepared_only': True, 'board_tested': False, 'start_allowed': False,
         'image_identity_sha256': sha(HERE / 'build/live-image-v3-id/identity.json'),
         'codec_manifest_sha256': sha(codec_path),
         'board_input_manifest_sha256': sha(OUT / 'input-manifest.json'),
         'tool_sha256': sha(Path(__file__)),
         'files_sha256': {name: sha(OUT / name) for name in ['live-image-identity-v1.json', 'codec-observation.json',
                                                          'fresh-fdt-before-boot.json', 'android-return-identity.json',
                                                          'unmount-audio-debug.json']}}
with (OUT / 'observation-preparation.json').open('xb') as stream:
    stream.write((json.dumps(proof, indent=2) + '\n').encode())
print(json.dumps(proof))
