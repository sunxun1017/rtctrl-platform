#!/usr/bin/env python3
"""Read-only copy of independently generated root evidence into our new directory."""
from pathlib import Path
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME = ROOT / 'outputs/rk3568-audio-runtime-20261005'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def members(path):
    result = {}
    for p in sorted(path.rglob('*')) if path.is_dir() else [path]:
        if p.is_symlink():
            raise ValueError('Review source symlink: ' + str(p))
        if p.is_file():
            result[p.relative_to(ROOT).as_posix()] = sha(p)
    return result


def main():
    out = HERE / 'review-evidence-v1'
    out.mkdir(exist_ok=False)
    originals = [RUNTIME / 'rerun-asoc-candidate-v2.py',
                 RUNTIME / 'build/root-asoc-candidate-v2',
                 RUNTIME / 'build/root-asoc-candidate-v1']
    before = {}
    for p in originals:
        before.update(members(p))
    if sha(originals[0]) != '8d9ed526b6c85e01c1d3cb87cf23f2c6e04590977c2db1a70b1822d358a4335c':
        raise ValueError('Wrong fresh runner')
    items = {}
    for p in originals:
        dst = out / p.name
        if p.is_dir():
            shutil.copytree(p, dst)
        else:
            shutil.copy2(p, dst)
        for original, digest in members(p).items():
            sub = Path(original).relative_to(p.relative_to(ROOT)) if p.is_dir() else Path()
            copied = dst / sub if p.is_dir() else dst
            if sha(copied) != digest:
                raise ValueError('Review copied SHA mismatch')
            items[original] = {'sha256': digest, 'snapshot': copied.relative_to(HERE).as_posix()}
    after = {}
    for p in originals:
        after.update(members(p))
    if before != after:
        raise ValueError('Root inputs changed during copy')
    result = json.loads((out / 'root-asoc-candidate-v2/result.json').read_text())
    if not result['all_six_fresh_compiles_and_runs_match']:
        raise ValueError('Fresh check did not pass narrow expected scope')
    manifest = {'schema': 'asoc-root-review-snapshot-v1', 'inputs': items,
                'root_inputs_unchanged': True, 'all_six_fresh_compiles_and_runs_match': True,
                'root_runner_sha256': sha(originals[0]),
                'root_result_sha256': sha(originals[1] / 'result.json'),
                'preserved_failed_v1': True, 'failed_v1_compiled': False,
                'board_tested': False, 'full_duplex_passed': False}
    (out / 'input-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'files_copied': len(items), 'originals_unchanged': True,
                     'result_sha256': manifest['root_result_sha256']}))


if __name__ == '__main__':
    main()
