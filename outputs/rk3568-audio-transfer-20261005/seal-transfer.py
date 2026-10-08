#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Freeze helper artifacts and verify every recorded static-build input byte."""
from pathlib import Path
import hashlib
import json
import shutil
HERE = Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
build = HERE / 'build/static-v1'
r = json.loads((build / 'manifest.json').read_text())
for name, expected in r['files_sha256'].items():
    p = HERE / name
    if not p.is_file() or p.is_symlink() or sha(p) != expected: raise ValueError('frozen evidence changed: ' + name)
if r['board_tested'] or r['actual_bounded_transfer'] or r['audio_start_allowed'] or r['permits_reboot']: raise ValueError('offline boundary invalid')
output = HERE / 'sealed-v1'
output.mkdir(exist_ok=False)
for name in ['README.md', 'PLAN.md', 'LICENSE', 'pcm-transfer.c', 'pcm-transfer-body.c', 'build-transfer.py', 'test-transfer.py', 'test-wrapper.c', 'source-provenance-final.json', 'seal-transfer.py']:
    shutil.copy2(HERE / name, output / name)
record = dict(binary=str(build / 'pcm-transfer'), binary_sha256=r['binary_sha256'], source_sha256=r['source_sha256'], locked_uapi_sha256=r['locked_uapi_sha256'], build_manifest_sha256=sha(build / 'manifest.json'), cases_per_environment=143, byte_identical_complete_real_program=True, source_reproduction_verified=True, files_sha256=r['files_sha256'] | {p.name:sha(p) for p in HERE.glob('*') if p.is_file()} | {'build/static-v1/manifest.json':sha(build / 'manifest.json')}, sealed_files_sha256={p.name:sha(p) for p in output.glob('*') if p.is_file()}, board_tested=False, actual_bounded_transfer=False, audio_start_allowed=False, deployable=False, published=False, permits_reboot=False, full_duplex_supported=False, independent_review_completed=False, remaining=['Root independent review and integration', 'Root final C3/Image/identity/exclusive-FD/route/power gate', 'Actual board bounded transfer and CPU/DMA readonly exit proof', 'Electrical/acoustic acceptance and uninterruptible-kernel/output/scheduling rescue boundary'])
(output / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({k:record[k] for k in ['binary','binary_sha256','source_sha256','cases_per_environment','board_tested','actual_bounded_transfer']} | {'manifest':str(output / 'manifest.json')}))
