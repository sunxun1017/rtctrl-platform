#!/usr/bin/env python3
"""Copy exactly the reviewed five params inputs and one card PM input."""
import hashlib
import json
import shutil
import stat
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARAMS = HERE.parent / 'full-duplex-params-candidate-v1'
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Nonordinary input ' + str(path))
    for parent in path.parents:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('Nonordinary ancestor ' + str(parent))
        if parent == ROOT:
            return path
    raise ValueError('Outside root')


def main():
    manifest_path = ordinary(PARAMS / 'source-manifest-v4.json')
    data = manifest_path.read_bytes()
    if sha(data) != '889c0e25655b29bbda10061b6f0ac569741b892a20cd0316695498442be8037c':
        raise ValueError('Params source revision drift')
    files = json.loads(data)['files']
    out = HERE / 'inputs-v1'
    out.mkdir()
    records = {}
    for rel, meta in files.items():
        source = ordinary(PARAMS / 'source-v4' / rel)
        content = source.read_bytes()
        if sha(content) != meta['candidate_sha256']:
            raise ValueError('Params source drift ' + rel)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        records[rel] = {'source': source.relative_to(ROOT).as_posix(),
                        'bytes': len(content), 'sha256': sha(content)}
    rel = 'sound/soc/soc-core.c'
    source = ordinary(SOURCE / rel)
    content = source.read_bytes()
    image_inventory = HERE.parent / 'build/integration-v4/integrated-source-inventory.json'
    expected = json.loads(ordinary(image_inventory).read_text())[rel]
    if expected['sha256'] != sha(content) or expected['bytes'] != len(content):
        raise ValueError('Finite actual card source/Image identity drift')
    (out / rel).write_bytes(content)
    records[rel] = {'source': source.relative_to(ROOT).as_posix(),
                   'bytes': len(content), 'sha256': sha(content)}
    (out / 'manifest.json').write_text(json.dumps({
        'scope': 'SIX_FINITE_INPUTS_ONLY_NO_BUILD',
        'params_manifest_sha256': sha(data),
        'files': records,
    }, indent=2) + '\n')
    shutil.copytree(out, HERE / 'source-v1', ignore=shutil.ignore_patterns('manifest.json'))
    print(json.dumps({'copied_inputs': len(records), 'compiler_executed': False}))


if __name__ == '__main__':
    main()
