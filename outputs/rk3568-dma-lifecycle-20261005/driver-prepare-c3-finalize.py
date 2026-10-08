#!/usr/bin/env python3
"""Create v8 after reproduced initial-ready and held-channel open failures."""
import difflib
import json
import subprocess
from pathlib import Path
from source_utils import function, sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / 'third_party/linux-rk3588'
COMMIT = '9f9e9d18574d0914c0d192a90c3babfe1fd63c95'


def exact(text, old, new):
    if text.count(old) != 1:
        raise ValueError('exact anchor missing: ' + old[:90])
    return text.replace(old, new, 1)


def main():
    for argv, wanted in [(['git', '-C', str(KERNEL), 'rev-parse', 'HEAD'], COMMIT), (['git', '-C', str(KERNEL), 'status', '--porcelain'], '')]:
        if subprocess.run(argv, check=True, capture_output=True, text=True).stdout.strip() != wanted:
            raise ValueError('locked original kernel gate rejected')
    parent = HERE / 'driver-source-c3-v7'
    old = json.loads((parent / 'manifest.json').read_text())
    after = {path: (parent / path).read_bytes() for path in old['source_sha256']}
    if any(sha(after[path]) != wanted for path, wanted in old['source_sha256'].items()):
        raise ValueError('parent source drift')
    if sha((parent / 'C3-lifecycle-review.patch').read_bytes()) != old['patch_sha256']:
        raise ValueError('parent patch drift')
    for name, counts in [('pl330-ready-tests-red-v1', (14, 13, 1)), ('dma-pcm-open-tests-red-v1', (21, 19, 2))]:
        result = json.loads((HERE / name / 'result.json').read_text())
        for run in result['runs'].values():
            if run['tests'] != dict(zip(['total', 'passed', 'failed'], counts)):
                raise ValueError('required reproduced failure absent')
    path = 'drivers/dma/pl330.c'
    text = after[path].decode()
    body = function(text, 'pl330_controller_stop_proof')
    new = exact(body, '\tspin_lock_irqsave(&pl330->lock, flags);\n\tret = pl330->lifecycle_error;', '\tspin_lock_irqsave(&pl330->lock, flags);\n\tpl330->stop_proven = false;\n\tret = pl330->lifecycle_error;')
    new = exact(new, '\n\t}\nout:', '\n\t}\n\tpl330_capture_stop_locked(pl330);\nout:')
    text = exact(text, body, new)
    point = function(text, 'pl330_synchronize_checked')
    callback = '''/* Held core channel references keep this controller alive during open. */
static int pl330_check_open(struct dma_chan *chan)
{
	struct dma_pl330_chan *pch = to_pchan(chan);
	struct pl330_dmac *pl330 = pch->dmac;
	unsigned long flags;
	int ret;

	/* Cached admission only: never acquire PM or touch hardware here. */
	spin_lock_irqsave(&pl330->lock, flags);
	ret = pl330->lifecycle_error;
	if (!ret && (pl330->removing || pl330->system_suspended ||
		     READ_ONCE(pl330->ddma.lifecycle_closing)))
		ret = -EBUSY;
	spin_unlock_irqrestore(&pl330->lock, flags);
	return ret;
}

'''
    text = exact(text, point, callback + point)
    text = exact(text, '\tpd->device_synchronize = pl330_synchronize;', '\tpd->device_synchronize = pl330_synchronize;\n\tpd->device_check_open = pl330_check_open;')
    after[path] = text.encode()
    path = 'include/linux/dmaengine.h'
    text = after[path].decode()
    text = exact(text, '\tint (*device_synchronize_checked)(struct dma_chan *chan);', '\tint (*device_synchronize_checked)(struct dma_chan *chan);\n\t/* Cached read-only open admission required by checked providers. */\n\tint (*device_check_open)(struct dma_chan *chan);')
    point = function(text, 'dmaengine_synchronize_checked')
    helper = '''/* Ordinary providers retain their original open contract. */
static inline int dmaengine_check_open(struct dma_chan *chan)
{
	if (!chan->device->device_synchronize_checked)
		return 0;
	if (!chan->device->device_check_open)
		return -EOPNOTSUPP;
	return chan->device->device_check_open(chan);
}

'''
    text = exact(text, point, helper + point)
    after[path] = text.encode()
    path = 'sound/core/pcm_dmaengine.c'
    text = after[path].decode()
    body = function(text, 'snd_dmaengine_pcm_open')
    new = exact(body, '\tif (!chan)\n\t\treturn -ENXIO;\n', '\tif (!chan)\n\t\treturn -ENXIO;\n\n\tret = dmaengine_check_open(chan);\n\tif (ret < 0)\n\t\treturn ret;\n')
    after[path] = exact(text, body, new).encode()
    frozen_b = ROOT / 'outputs/rk3568-asoc-errors-20261005/driver-source-v2'
    before = {path: ((frozen_b if path in ['sound/soc/soc-pcm.c', 'sound/core/pcm_native.c'] else KERNEL) / path).read_bytes() for path in after}
    if any(sha(before[path]) != wanted for path, wanted in old['before_sha256'].items()):
        raise ValueError('incremental base drift')
    patch = ''
    for path, data in after.items():
        if data != before[path]:
            patch += 'diff --git a/' + path + ' b/' + path + '\n'
            patch += ''.join(difflib.unified_diff(before[path].decode().splitlines(True), data.decode().splitlines(True), fromfile='a/' + path, tofile='b/' + path))
    out = HERE / 'driver-source-c3-v8'
    out.mkdir(exist_ok=False)
    for path, data in after.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (out / 'C3-lifecycle-review.patch').write_text(patch)
    manifest = {
        **old,
        'phase': 'Initial complete STOP cached proof and read-only held-channel open admission; independent review pending',
        'parent_manifest_sha256': sha((parent / 'manifest.json').read_bytes()),
        'parent_source_sha256': old['source_sha256'],
        'source_sha256': {path: sha(data) for path, data in after.items()},
        'patch_sha256': sha(patch.encode()),
        'generator_sha256': {name: sha((HERE / name).read_bytes()) for name in ['driver-prepare-c3-finalize.py', 'source_utils.py']},
        'red_results_sha256': {name: sha((HERE / name / 'result.json').read_bytes()) for name in ['pl330-ready-tests-red-v1', 'dma-pcm-open-tests-red-v1']},
        'readonly_open_contract': 'Only checked providers require device_check_open; absent checked callback retains legacy open, incomplete checked returns EOPNOTSUPP. PL330 reads cached sticky/closed state under controller lock without PM/MMIO.',
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'output': str(out), 'pl330_sha256': manifest['source_sha256']['drivers/dma/pl330.c'], 'patch_sha256': manifest['patch_sha256'], 'deployable': False}))


if __name__ == '__main__':
    main()

