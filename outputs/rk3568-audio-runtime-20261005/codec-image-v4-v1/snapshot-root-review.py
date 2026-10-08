#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy the completed root's read-only audit; never write its original files."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ROOT_RECEIPT_SHA = 'bfbba6268dc8934a3b59585983c554f076cc7252dd5d62566fbc9216a148a518'
ROOT_TOOL_SHA = 'd762c989e050fb06cc7b5f9d66257961cde638b415513ed9716611214c2c4456'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    spec = importlib.util.spec_from_file_location('reviewed_codec_builder', HERE / 'codec_builder.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    audit = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/root-codec-image-v4-audit-v1'
    tool = ROOT / 'outputs/rk3568-audio-runtime-20261005/audit-codec-image-v4-v1.py'
    builder.require(sha(builder.ordinary(audit / 'receipt.json')) == ROOT_RECEIPT_SHA and
                    sha(builder.ordinary(tool)) == ROOT_TOOL_SHA, 'Root audit changed')
    receipt = json.loads((audit / 'receipt.json').read_text())
    builder.require(receipt['root_fresh_actual_codec_audit_passed'] and
                    not receipt['board_tested'] and not receipt['START_authorized'] and
                    receipt['root_audit_tool_sha256'] == ROOT_TOOL_SHA and
                    not receipt['module_recompiled_during_root_audit'], 'Root review scope changed')
    sources = [tool, *sorted(audit.rglob('*'))]
    sources = [p for p in sources if not stat.S_ISDIR(p.lstat().st_mode)]
    out = HERE / 'review-evidence-v1'
    builder.fresh(out)
    out.mkdir()
    records = {}
    for p in sources:
        builder.ordinary(p)
        relative = ('root-audit/' + p.relative_to(audit).as_posix()) if p.is_relative_to(audit) else p.name
        dest = out / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        before = {'sha256': sha(p), 'bytes': p.stat().st_size, 'mode': stat.S_IMODE(p.lstat().st_mode)}
        shutil.copy2(p, dest)
        builder.ordinary(dest)
        builder.require(sha(dest) == before['sha256'] and dest.stat().st_size == before['bytes'] and
                        stat.S_IMODE(dest.lstat().st_mode) == before['mode'], 'Root snapshot copy changed')
        records[p.relative_to(ROOT).as_posix()] = {**before, 'snapshot': relative}
    for name, item in records.items():
        p = builder.ordinary(ROOT / name)
        builder.require(sha(p) == item['sha256'] and p.stat().st_size == item['bytes'] and
                        stat.S_IMODE(p.lstat().st_mode) == item['mode'], 'Root original changed during copy')
    record = {'schema': 'root_fresh_codec_readonly_audit_snapshots_v1', 'inputs': records,
              'ordinary_file_count': len(records), 'root_originals_unchanged': True,
              'root_audit_receipt_sha256': ROOT_RECEIPT_SHA, 'root_audit_tool_sha256': ROOT_TOOL_SHA,
              'module_recompiled_during_snapshot': False, 'board_tested': False,
              'generated_inventory_was_signed_at_Image_compile_time': False}
    (out / 'input-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'copied_ordinary_files': len(records), 'manifest_sha256': sha(out / 'input-manifest.json')}))


if __name__ == '__main__':
    main()
