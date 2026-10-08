#!/usr/bin/env python3
"""Preserve r1 compiler failures and repair only mock type/warning-policy boundaries."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
MODEL_SHA = '07b6e6cd407d6c0e5d0772929d7a05fb9995bf8aaa3a09a5ccfc3bc869a5e84e'
RUNNER_SHA = 'ca0850a477ebbdca9354af9208e097a16465656d290e749adfc6a785301fd474'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    old = HERE / 'model-v1'
    if sha(old / 'input-manifest.json') != MODEL_SHA or sha(HERE / 'run-model.py') != RUNNER_SHA:
        raise ValueError('Reviewed r1 identity changed')
    inputs = json.loads((old / 'input-manifest.json').read_text())
    actual = {p.relative_to(old).as_posix(): sha(p) for p in old.rglob('*') if p.is_file() and p.name != 'input-manifest.json'}
    if actual != inputs['model_files_sha256']:
        raise ValueError('Original model changed')
    failure = HERE / 'runs-baselinev1/receipt.json'
    failed = json.loads(failure.read_text())
    if any(row['compile']['exit'] != 1 or 'execution' in row for row in failed['model_runs'].values()):
        raise ValueError('Expected original compiler-only failure')
    source = HERE.parent / 'full-duplex-configuration-design-v1/inputs-v1/soc.h'
    text = source.read_text()
    if 'unsigned int num_codecs;\n\tunsigned int num_cpus;' not in text or '\tint num_components;' not in text:
        raise ValueError('Actual runtime count types changed')
    out = HERE / 'model-v2'
    shutil.copytree(old, out)
    path = out / 'model-glue.h'
    text = path.read_text()
    original = '    int num_components, num_cpus, num_codecs;'
    if text.count(original) != 1:
        raise ValueError('Expected mock count declaration missing')
    path.write_text(text.replace(original, '    int num_components;\n    unsigned int num_cpus, num_codecs;'))
    runner = (HERE / 'run-model.py').read_text()
    original = "'-Wno-unused-parameter', '-Wno-unused-function', '-pthread'"
    if runner.count(original) != 1:
        raise ValueError('Expected compiler warning arguments missing')
    runner = runner.replace(original, "'-Wno-unused-parameter', '-Wno-unused-function', '-Wno-sign-compare', '-pthread'")
    (HERE / 'run-model-r2.py').write_text(runner)
    changed = {p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p.name != 'input-manifest.json' and sha(p) != actual[p.relative_to(out).as_posix()]}
    if changed != {'model-glue.h'} or sha(out / 'unit.c') != sha(old / 'unit.c') or sha(out / 'actual-params-functions.c') != sha(old / 'actual-params-functions.c'):
        raise ValueError('Unexpected model correction scope')
    inputs['r2_harness_correction'] = {'previous_model_manifest_sha256': MODEL_SHA,
        'previous_runner_sha256': RUNNER_SHA, 'compiler_failure_receipt_sha256': sha(failure),
        'changed_model_files': ['model-glue.h'], 'actual_rtd_types_source_sha256': sha(source),
        'warning_scope': 'Only -Wno-sign-compare added to -Wall -Wextra -Werror API-model build. Actual kernel normal warning policy does not promote this warning. No production body changed.',
        'production_bodies_unchanged': True, 'contracts_unchanged': True,
        'correction_tool_sha256': sha(Path(__file__)), 'r2_runner_sha256': sha(HERE / 'run-model-r2.py')}
    inputs['model_files_sha256'] = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'input-manifest.json'}
    (out / 'input-manifest.json').write_text(json.dumps(inputs, indent=2) + '\n')
    print(json.dumps({'model_v2_manifest_sha256': sha(out / 'input-manifest.json'),
        'runner_r2_sha256': sha(HERE / 'run-model-r2.py'), 'production_bodies_unchanged': True,
        'model_compiled': False, 'model_executed': False}))


if __name__ == '__main__':
    main()
