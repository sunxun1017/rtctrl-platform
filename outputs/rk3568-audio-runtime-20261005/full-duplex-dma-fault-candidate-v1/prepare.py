#!/usr/bin/env python3
"""Finite locked baseline copies; no SDK mutation or recursive inventory."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SDK = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4'
LOCKS = {
    'drivers/dma/pl330.c': 'ac40d2e3c41116667f2ef147b1f644c9782d26cd8f1597628afa67bd50f93b16',
    'sound/core/pcm_dmaengine.c': 'bd59d7377ec377f4c671cf0fa11331ba6795113d88c42b91c35be614085392ac',
}
FILES = list(LOCKS) + ['sound/soc/soc-generic-dmaengine-pcm.c',
                      'include/sound/dmaengine_pcm.h', 'drivers/dma/dmaengine.h',
                      'include/linux/dmaengine.h', 'sound/core/pcm_memory.c']
records = {}
for name in FILES:
    data = (SDK / name).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if name in LOCKS and digest != LOCKS[name]:
        raise ValueError('Baseline drift: ' + name)
    target = HERE / 'baseline' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError('Fresh baseline required')
    target.write_bytes(data)
    records[name] = {'bytes': len(data), 'sha256': digest}
(HERE / 'baseline-manifest.json').write_text(json.dumps(records, indent=2) + '\n')
print(json.dumps({'finite_inputs': len(records), 'SDK_modified': False}))
