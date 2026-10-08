#!/usr/bin/env python3
"""Copy only five reviewed sources; do not modify product sources."""
import hashlib, json, os
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4'
INPUTS = {
    'include/sound/soc-dai.h': '03c5171491ed638d413b22ba05a58fe0ec08d48f53bead29c92d36c3595ad748',
    'sound/soc/soc-pcm.c': '9ba2247294f745488133b3d0b307686249b4c2cd23045ea1bfba517dd57aed37',
    'sound/soc/generic/simple-card-utils.c': '4b2094f708f5bec2b73938ec217eedae67f5df962ee0847bee8f2c29eddbcd73',
    'sound/soc/rockchip/rockchip_i2s_tdm.c': '7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141',
    'sound/soc/codecs/rk817_codec.c': '72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64',
}
def sha(data): return hashlib.sha256(data).hexdigest()
def ordinary(p):
    for part in (p, *p.parents):
        if part.is_symlink(): raise ValueError('symlink input: ' + str(part))
    if not p.is_file(): raise ValueError('not regular: ' + str(p))
    return p.read_bytes()
def main():
    out = HERE / 'inputs-v1'
    if out.exists(): raise ValueError('fresh output required')
    inventory_path = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/integration-v4/integrated-source-inventory.json'
    ib = ordinary(inventory_path)
    if sha(ib) != 'bb2fb1a0c548bb2de8e683ebd6540f3cb75ddb5815af3df7cf2f8a1d918d0cd3': raise ValueError('Image inventory drift')
    image = json.loads(ib)
    staged = {}
    for rel, expected in INPUTS.items():
        p = SOURCE / rel; data = ordinary(p)
        if sha(data) != expected: raise ValueError('source drift: ' + rel)
        item = image[rel]
        if item['sha256'] != expected or item['bytes'] != len(data): raise ValueError('Image entry drift: ' + rel)
        mode = p.stat().st_mode & 0o777
        if item['mode'] != ('100755' if mode & 0o111 else '100644'): raise ValueError('source mode: ' + rel)
        staged[rel] = (data, mode)
    out.mkdir()
    manifest = {'scope': 'FIVE_ORDINARY_SOURCE_COPIES_NOT_BUILD_OR_BOARD', 'source': str(SOURCE), 'image_inventory_sha256': sha(ib), 'inputs': {}}
    for rel, (data, mode) in staged.items():
        p = out / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); p.chmod(mode)
        if ordinary(p) != data: raise ValueError('copy drift')
        manifest['inputs'][rel] = {'sha256': sha(data), 'bytes': len(data), 'linux_mode': mode, 'image_inventory': image[rel]}
    manifest['documents'] = {}
    for p in (HERE / 'INTERFACE-DESIGN.md', HERE / 'PLAN.md', ROOT / 'outputs/rk3568-audio-runtime-20261005/full-duplex-params-baseline-v1/runs-baselinev2/receipt.json', ROOT / 'outputs/rk3568-audio-runtime-20261005/full-duplex-params-baseline-v1/execution-readback-v3/receipt.json'):
        data = ordinary(p); manifest['documents'][str(p.relative_to(ROOT))] = {'bytes': len(data), 'sha256': sha(data)}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'copied_sources': 5, 'manifest_sha256': sha((out / 'manifest.json').read_bytes()), 'no_build': True}))
if __name__ == '__main__': main()
