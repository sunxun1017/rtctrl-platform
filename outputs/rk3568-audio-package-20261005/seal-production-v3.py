#!/usr/bin/env python3
"""Freeze new tools, actual new production bundle and all observed v3 checks."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GATE = 'outputs/rk3568-audio-runtime-20261005/build/review-gate-v3.json'


def main():
    spec = importlib.util.spec_from_file_location('seal_v3', HERE / 'audio-package-v3.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    inputs = core.production_inputs(GATE)
    report = core.audit_directory(HERE / 'build/ram-audio-v3', inputs)
    audit = core.unique_json(core.read_ordinary(HERE / 'build/audit-production-v3/audit.json'))
    core.require(report == audit, 'Actual v3 audit equals fresh full audit')
    old_data = core.read_ordinary(HERE / 'build/old-inputs-v3/manifest.json')
    old = core.unique_json(old_data)
    for name, sha in old['files_sha256'].items():
        core.require(core.metadata(core.read_ordinary(HERE / name))['sha256'] == sha, 'Old v1/v2 changed: ' + name)
    receipts = {}
    for name, count in [('transition-red-v2', 4), ('transition-green-v3-review1', 4), ('policy-models-v3-review1', 25),
                        ('closure-red-v3', 3), ('closure-green-v3', 3),
                        ('elf-helper-old-v3', 2), ('fixture-regression-v3', 62), ('production-inputs-v3', 23)]:
        path = HERE / 'build' / name / 'result.json'
        data = core.read_ordinary(path)
        result = core.unique_json(data)
        expected_passed = 0 if name == 'transition-red-v2' else (1 if name == 'closure-red-v3' else count)
        core.require(result['total'] == count and result['passed'] == expected_passed,
                     'Observed exact v3 checks: ' + name)
        if 'core_source' in result and name != 'closure-red-v3':
            core.require(result['core_source'] == core.metadata(core.read_ordinary(HERE / 'audio-package-v3.py')),
                         'Observed check exact current source: ' + name)
        if name == 'transition-green-v3-review1':
            core.require(result['core_sha256'] == core.metadata(core.read_ordinary(HERE / 'audio-package-v3.py'))['sha256'],
                         'Observed transition current source')
        receipts[name] = core.metadata(data)
    cli = core.unique_json(core.read_ordinary(HERE / 'build/production-cli-v3/result.json'))
    core.require(len(cli['commands']) == 2 and all(item['exit_code'] == 0 for item in cli['commands']), 'Observed actual v3 CLI')
    core.require(cli['package_manifest'] == {'path': 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/manifest.json',
                 'bytes': len(core.read_ordinary(HERE / 'build/ram-audio-v3/manifest.json')),
                 'sha256': core.metadata(core.read_ordinary(HERE / 'build/ram-audio-v3/manifest.json'))['sha256']}, 'Actual CLI package identity')
    out = core.fresh_directory(HERE / 'build/sealed-production-v3')
    tools = ('audio-package-v3.py', 'build-audio-package-v3.py', 'audit-audio-package-v3.py',
             'test-audio-package-v3.py', 'test-production-inputs-v3.py', 'test-v3-transition.py', 'test-policy-v3.py', 'test-runtime-closure-v3.py', 'test-elf-helper-v3.py',
             'create-v3-tools.py', 'runtime-policy-v3.inc.py', 'replay-tools-v3.py', 'run-production-v3.py', 'run-tests-v3.py', 'seal-production-v3.py', 'README-v3.md', 'PLAN-v3.md')
    snapshots = {str((HERE / name).relative_to(ROOT)): core.read_ordinary(HERE / name) for name in tools}
    input_names = (GATE, core.PRODUCTION + 'manifest.json', core.PRODUCTION + 'kernel.config',
                   core.PRODUCTION + 'Module.symvers', core.PRODUCTION + 'vmlinux.symvers',
                   core.RUNTIME + 'build/integrated-codec-v2/manifest.json',
                   core.RUNTIME + 'session-guard-v4/build/manifest.json', core.RUNTIME + 'session-guard-v4/frozen-output-manifest.json',
                   core.RUNTIME + 'cpu-lifecycle-v11/source/manifest.json', core.RUNTIME + 'cpu-lifecycle-v11/frozen-output-manifest.json',
                   'outputs/rk3568-pid1-20261005/build/production-v3/manifest.json',
                   'outputs/rk3568-rcu-reset-20261004/kernel-artifacts.json')
    snapshots.update({name: core.read_ordinary(core.relative_path(name), 8 * 1024 * 1024) for name in input_names})
    for name, data in snapshots.items():
        target = out / 'source-inputs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        core.write_new(target, data)
    evidence = {}
    for name in ('old-inputs-v3', 'transition-red-v2', 'transition-green-v3', 'policy-models-v3',
                 'transition-green-v3-review1', 'policy-models-v3-review1', 'closure-red-v3', 'closure-green-v3', 'elf-helper-old-v3', 'fixture-regression-v3',
                 'production-inputs-v3', 'fixture-tests-cli-v3', 'production-tests-cli-v3',
                 'production-cli-v3', 'ram-audio-v3', 'audit-production-v3'):
        for path in sorted((HERE / 'build' / name).rglob('*')):
            if path.is_file() and not path.is_symlink():
                evidence[path.relative_to(ROOT).as_posix()] = core.metadata(core.read_ordinary(path))
    for path in sorted((HERE / 'build').glob('codec-elf-audit-v3-*/*')):
        if path.is_file() and not path.is_symlink():
            evidence[path.relative_to(ROOT).as_posix()] = core.metadata(core.read_ordinary(path))
    receipt = {'schema': 3, 'status': 'RAM_ONLY_NOT_FLASH_READY', 'sources': {name: core.metadata(data) for name, data in snapshots.items()},
               'results': evidence, 'observed_checks': receipts, 'package': report['package'], 'raw_bytes': report['raw_bytes'],
               'runtime': inputs['runtime'], 'Image_manifest': inputs['image_manifest'], 'review_gate': inputs['review_gate'],
               'old_preserved_ordinary_files': old['count'], 'old_input_inventory': core.metadata(old_data),
               'board_tested': False, 'physical_sound_verified': False, 'deployed': False, 'formal_flash_ready': False,
               'audio_start_allowed': False, 'fresh_addresses_verified': False,
               'freeze_scope': 'NEW_TOOLS_INPUT_MANIFEST_SNAPSHOTS_AND_FULL_SHA_REFERENCES_TO_EXTERNAL_BUNDLE_AND_EXECUTED_CHECKS',
               'bundle_binary_bytes_copied_inside_this_seal': False,
               'external_references_freshly_verified': True}
    core.write_new(out / 'receipt.json', core.json_bytes(receipt))
    references = {name: info['sha256'] for name, info in {**receipt['sources'], **evidence}.items()}
    core.verify_hash_map(references)
    core.write_new(out / 'external-references-sha256.json', core.json_bytes({'root': 'REPOSITORY', 'files_sha256': references}))
    inventory = {p.relative_to(out).as_posix(): core.metadata(core.read_ordinary(p))['sha256'] for p in sorted(out.rglob('*')) if p.is_file()}
    core.write_new(out / 'frozen-output-manifest.json', core.json_bytes({'schema': 3, 'files_sha256': inventory}))
    inventory['frozen-output-manifest.json'] = core.metadata(core.read_ordinary(out / 'frozen-output-manifest.json'))['sha256']
    core.write_new(out / 'SHA256SUMS', ''.join(sha + '  ' + name + '\n' for name, sha in sorted(inventory.items())).encode())
    print(core.json_bytes({'sealed_files': len(inventory), 'old_preserved': old['count'], 'package': report['package'],
                         'receipt': core.metadata(core.read_ordinary(out / 'receipt.json')),
                         'inventory': core.metadata(core.read_ordinary(out / 'frozen-output-manifest.json')),
                         'SHA256SUMS': core.metadata(core.read_ordinary(out / 'SHA256SUMS'))}).decode())


if __name__ == '__main__':
    main()
