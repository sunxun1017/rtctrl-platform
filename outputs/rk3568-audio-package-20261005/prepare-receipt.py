#!/usr/bin/env python3
"""Seal prepared sources and observed fixture evidence, never a final Image claim."""
import argparse
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('audio_prepared_receipt', HERE / 'audio-package.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    _, dependencies = core.dependencies()
    fixed = core.fixed_inputs()
    test_path = HERE / 'build/tests-v3/result.json'
    test_data = core.read_ordinary(test_path)
    tests = core.unique_json(test_data)
    core.require(tests['passed'] == tests['total'] == 62 and
                 all(case['passed'] is True for case in tests['cases']), 'Complete observed fixture suite required')
    core.require(tests['core_source'] == core.metadata(core.read_ordinary(HERE / 'audio-package.py')) and
                 tests['test_source'] == core.metadata(core.read_ordinary(HERE / 'test-audio-package.py')),
                 'Tests differ from prepared source')
    output = core.fresh_directory(args.out)
    sources = dict(dependencies)
    for path in sorted(HERE.iterdir()):
        if path.suffix in ('.py', '.md') and path.is_file():
            sources[str(path.relative_to(core.ROOT))] = core.read_ordinary(path)
    for name, data in sources.items():
        target = output / 'source-inputs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        core.write_new(target, data)
    evidence = {}
    for name in ['build/address-red-v1/result.json', 'build/manifest-red-v1/result.json',
                 'build/base-bank-red-v1/result.json', 'build/tests-v1/result.json',
                 'build/tests-v2/result.json', 'build/tests-v3/result.json',
                 'build/tests-v3/fixture-candidate/receipt.json']:
        data = core.read_ordinary(HERE / name)
        evidence[name] = core.metadata(data)
        target = output / 'evidence' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        core.write_new(target, data)
    production_manifest = core.ROOT / (core.PRODUCTION + 'manifest.json')
    receipt = {'schema': 1, 'status': 'SOURCES_AND_FIXTURE_POLICY_PREPARED_PRODUCTION_PENDING',
               'sources': {name: core.metadata(data) for name, data in sources.items()}, 'evidence': evidence,
               'fixed_inputs': {name: {'path': core.FIXED[name][0], **core.metadata(data)}
                                for name, data in fixed.items()},
               'fixture_checks': {'passed': 62, 'total': 62, 'production_Image_not_used': True},
               'production_manifest_observed_present': production_manifest.exists(),
               'production_package_generated': False, 'board_tested': False, 'formal_flash_ready': False}
    core.write_new(output / 'receipt.json', core.json_bytes(receipt))
    print(core.json_bytes({'status': receipt['status'], 'sources': len(sources), 'evidence': len(evidence),
                           'production_manifest_observed_present': receipt['production_manifest_observed_present'],
                           'receipt': core.metadata((output / 'receipt.json').read_bytes())}).decode())


if __name__ == '__main__':
    main()
