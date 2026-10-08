#!/usr/bin/env python3
"""Freshly compile/run the two v7 failures and their v8 CPU/PCM chain."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FROZEN = ROOT / 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv, output, label, env):
    with (output / (label + '.stdout')).open('wb') as stdout, (output / (label + '.stderr')).open('wb') as stderr:
        result = subprocess.run(argv, stdout=stdout, stderr=stderr, env=env, timeout=45)
    record = {'argv': argv, 'returncode': result.returncode,
              'stdout_sha256': sha(output / (label + '.stdout')),
              'stderr_sha256': sha(output / (label + '.stderr'))}
    (output / (label + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    assert result.returncode == 0, label
    return record


def main():
    output = HERE / 'build/c3-v8-root-reexecution-v1'
    output.mkdir(exist_ok=False)
    assert sha(FROZEN / 'receipt.json') == '97011370d4a66b385ab3855fa9cf2f2cf4c857728a1f969902f5e8dd9b10e975'
    receipt = json.loads((FROZEN / 'receipt.json').read_text())
    all_runs = {}
    env = dict(os.environ)
    env['ASAN_OPTIONS'] = 'detect_leaks=1:halt_on_error=1'
    env['UBSAN_OPTIONS'] = 'halt_on_error=1'
    for suite in ['pl330-ready2-tests-green-v2', 'dma-pcm-open-tests-green-v1', 'trigger-cpu-open-tests-green-v1']:
        source_dir = FROZEN / 'tests' / suite
        for name, expected in receipt['files_sha256'].items():
            if name.startswith('tests/' + suite + '/'):
                assert sha(FROZEN / name) == expected, name
        observed = json.loads((source_dir / 'result.json').read_text())
        suite_out = output / suite
        suite_out.mkdir()
        all_runs[suite] = {}
        for mode, old_run in observed['runs'].items():
            binary = suite_out / mode
            compile_argv = list(old_run['compile']['argv'])
            compile_argv[compile_argv.index('-o') + 1] = str(binary)
            compile_argv = [str(source_dir / 'real-functions.c') if x.endswith('/real-functions.c') else x for x in compile_argv]
            compiled = run(compile_argv, suite_out, mode + '-compile', env)
            old_exec = old_run['execution']['argv']
            exec_argv = [str(binary)] if len(old_exec) == 1 else [old_exec[0], str(binary)]
            executed = run(exec_argv, suite_out, mode + '-execute', env)
            tests = json.loads((suite_out / (mode + '-execute.stdout')).read_text().strip())
            assert tests == old_run['tests'] and tests['failed'] == 0, (suite, mode, tests)
            all_runs[suite][mode] = {'compile': compiled, 'execution': executed, 'tests': tests,
                                     'binary_sha256': sha(binary), 'fixture_result_sha256': sha(source_dir / 'result.json')}
            print(suite, mode, tests, flush=True)
    result = {'passed': True, 'runs': all_runs, 'c3_receipt_sha256': sha(FROZEN / 'receipt.json'),
              'reexecutor_sha256': sha(Path(__file__)), 'asan_options': env['ASAN_OPTIONS'],
              'ubsan_options': env['UBSAN_OPTIONS'], 'board_tested': False,
              'scope': 'Fresh compilations of frozen actual-function fixtures; scheduler/PM/register models remain software boundaries.'}
    result['files_sha256'] = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('ROOT_V8_FRESH_CONTRACTS_PASSED', flush=True)


if __name__ == '__main__':
    main()
