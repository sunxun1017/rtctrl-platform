#!/usr/bin/env python3
"""Verify every sealed file and all final test/output/object bindings after copy."""
import hashlib
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
REVIEW = HERE / 'C3-review-v2'
EXPECTED = '97011370d4a66b385ab3855fa9cf2f2cf4c857728a1f969902f5e8dd9b10e975'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    receipt_path = REVIEW / 'receipt.json'
    require(digest(receipt_path) == EXPECTED, 'receipt identity mismatch')
    receipt = json.loads(receipt_path.read_text())
    for name, wanted in receipt['files_sha256'].items():
        require(digest(REVIEW / name) == wanted, 'sealed file drift: ' + name)
    counts = {}
    for item in receipt['green_results']:
        folder = REVIEW / 'tests' / item['directory']
        result_path = folder / 'result.json'
        require(digest(result_path) == item['result_sha256'], 'result drift')
        result = json.loads(result_path.read_text())
        require(result['passed'] is True, 'not passing')
        require(set(result['runs']) == {'host', 'host-sanitized', 'aarch64'}, 'missing environment')
        for env, run in result['runs'].items():
            expected_tests = {'total': item['tests_per_environment'], 'passed': item['tests_per_environment'], 'failed': 0}
            require(run['tests'] == expected_tests, 'count mismatch')
            require(json.loads((folder / (env + '.stdout')).read_text()) == expected_tests, 'stdout mismatch')
            for stage, stem in [('compile', env + '-compile'), ('execution', env)]:
                require(run[stage]['returncode'] == 0, 'nonzero command')
                require(isinstance(run[stage]['argv'], list) and run[stage]['argv'], 'argv absent')
                for suffix in ['stdout', 'stderr']:
                    require(digest(folder / (stem + '.' + suffix)) == run[stage][suffix + '_sha256'], 'stdio digest mismatch')
            binary = run['execution']['argv'][-1].rsplit('/', 1)[-1]
            require(digest(folder / binary) == run['binary_sha256'], 'ELF drift')
        counts[item['directory']] = item['tests_per_environment']
    production = json.loads((REVIEW / receipt['production_result']).read_text())
    require(production['objects_build_passed'] and len(production['objects_sha256']) == 12, 'object coverage missing')
    require(len(production['kbuild_commands_sha256']) == 12, 'actual compiler command coverage missing')
    for table in ['objects_sha256', 'kbuild_commands_sha256']:
        for name, wanted in production[table].items():
            require(digest(REVIEW / 'production/build' / name) == wanted, 'Kbuild drift')
    require(production['source_sha256'] == receipt['source_sha256'], 'production source mismatch')
    require(sum(counts.values()) == 183 == receipt['tests_per_environment'], 'suite total mismatch')
    result = {'passed': True, 'receipt_sha256': EXPECTED, 'sealed_files_verified': len(receipt['files_sha256']), 'tests_per_environment': 183, 'counts': counts, 'objects_verified': 12, 'actual_object_commands_verified': 12, 'published': False, 'deployable': False, 'board_tested': False, 'image_built': False}
    (HERE / 'finalize-seal-check-v1.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
