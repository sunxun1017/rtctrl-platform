#!/usr/bin/env python3
"""Copy the parent's final limited acceptance note without changing its origin."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPECTED = '797e51e4f62190dc9c389d4a1624293c705b8c2bf78b5166fe0c01ddd55354db'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    spec = importlib.util.spec_from_file_location('reviewed_codec_builder', HERE / 'codec_builder.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    source = builder.ordinary(ROOT / 'outputs/rk3568-audio-runtime-20261005/REVIEW-CODEC-IMAGE-v4-20261006.md')
    builder.require(sha(source) == EXPECTED, 'Final parent note changed')
    out = HERE / 'review-evidence-v2'
    builder.fresh(out)
    out.mkdir()
    target = out / source.name
    mode, size = stat.S_IMODE(source.lstat().st_mode), source.stat().st_size
    shutil.copy2(source, target)
    builder.ordinary(target)
    builder.require(sha(target) == sha(source) == EXPECTED and source.stat().st_size == target.stat().st_size == size
                    and stat.S_IMODE(source.lstat().st_mode) == stat.S_IMODE(target.lstat().st_mode) == mode,
                    'Final parent note snapshot changed')
    record = {'source': source.relative_to(ROOT).as_posix(), 'snapshot': target.name, 'sha256': EXPECTED,
              'bytes': size, 'mode': mode, 'root_original_unchanged': True,
              'scope': 'Parent limited offline integration acceptance; no board/START/unload authorization'}
    (out / 'input-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'manifest_sha256': sha(out / 'input-manifest.json'), 'root_note_sha256': EXPECTED}))


if __name__ == '__main__':
    main()
