#!/usr/bin/env python3
import difflib
import json
import subprocess
from pathlib import Path
from source_utils import sha
from pl330_probe_changes import apply
here = Path(__file__).resolve().parent
root = here.parents[1]
summary = {}
for version in ['v6', 'v7']:
    source = here / ('driver-source-c3-' + version)
    manifest = json.loads((source / 'manifest.json').read_text())
    text = (source / 'drivers/dma/pl330.c').read_text()
    summary[version] = {
        'source_hashes_match': all(sha((source / path).read_bytes()) == digest for path, digest in manifest['source_sha256'].items()),
        'patch_hash_matches': sha((source / 'C3-lifecycle-review.patch').read_bytes()) == manifest['patch_sha256'],
        'generator_hashes_match': {name: sha((here / name).read_bytes()) == digest for name, digest in manifest['generator_sha256'].items()},
        'pl330_del_index': text.index('static void pl330_del('),
        'block_definition_index': text.index('struct pl330_desc_block {'),
        'failstop_prototype_index': text.index('static void __noreturn pl330_failstop('),
    }
left = (here / 'driver-source-c3-v6/drivers/dma/pl330.c').read_text()
right = (here / 'driver-source-c3-v7/drivers/dma/pl330.c').read_text()
summary['v6_v7_source_equal'] = left == right
summary['v7_matches_current_generator'] = apply((here / 'driver-source-c3-v5/drivers/dma/pl330.c').read_text()) == right
summary['v6_v7_diff'] = ''.join(difflib.unified_diff(left.splitlines(True), right.splitlines(True), fromfile='v6', tofile='v7'))
summary['production_v8_errors'] = [line for line in (here / 'production-v8/objects.stdout').read_text().splitlines() if 'error:' in line or 'implicit declaration' in line][:30]
summary['latest_tests'] = {}
for prefix in ['pl330-c3-probe-tests-green-', 'dma-pcm-probe-tests-green-', 'pl330-probe-tests-green-', 'pl330-c3-hw-tests-green-', 'dma-admission-tests-green-', 'pcm-tests-memory-green-', 'trigger-cpu-tests-green-']:
    folders = sorted([p for p in here.iterdir() if p.is_dir() and p.name.startswith(prefix) and (p / 'result.json').exists()], key=lambda p: int(p.name.rsplit('v', 1)[-1]))
    if folders:
        folder = folders[-1]
        result = json.loads((folder / 'result.json').read_text())
        summary['latest_tests'][folder.name] = {env: run.get('tests') for env, run in result['runs'].items()}
summary['root_git_status'] = subprocess.run(['git', '-C', str(root), 'status', '--short'], capture_output=True, text=True, check=True).stdout.splitlines()[:100]
(here / 'finalize-inspect-v2.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))

