#!/usr/bin/env python3
"""Bind CPU v12, fresh root executions, and a new private Image build."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CPU = HERE / 'cpu-lifecycle-v12'
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
SOURCE_SHA = '7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141'
DELTA_SHA = '64957ca517417c02dbb7c2a52306bb3020f5b2b730cdf636a0f60fbd950a078c'
INVENTORY_SHA = '46b7d7851a135de4943303ea62ae3c6abe5e207d3f1390f4a4c5b333f7b5e8c8'
ADDENDUM_SHA = 'b0f9e8516ff927a4025c459dc15288ec294db301c6f313dc27bf8594f0c954ed'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh_write(path, content):
    with path.open('xb') as stream:
        stream.write(content.encode())


def replace_once(content, old, new):
    if content.count(old) != 1:
        raise ValueError('Unique anchor required: ' + old[:100])
    return content.replace(old, new, 1)


def body(source, name):
    match = re.search(r'^[A-Za-z_][A-Za-z_0-9 \t*]*\b' + name + r'\([^;{}]*?\)\s*\{', source, re.M)
    if match is None:
        raise ValueError('Missing actual function: ' + name)
    depth = 0
    for end in range(source.index('{', match.start()), len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if depth == 0:
            return source[match.start():end + 1]
    raise ValueError('Unterminated function: ' + name)


def main():
    previous_path = HERE / 'build/review-gate-v3.json'
    if sha(previous_path) != '56ec8e396811c6b970ebb693db1fbd14b484fd4e54c321a011431201062e7af6':
        raise ValueError('Previous reviewed gate changed')
    previous = json.loads(previous_path.read_text())
    if not previous['accepted_for_offline_integration'] or not previous['cpu_v11_independent_review_completed']:
        raise ValueError('Prior acceptance required')
    bound = dict(previous['files_sha256'])
    inventories = [
        (CPU, INVENTORY_SHA, 2287),
        (CPU / 'post-freeze-review-v1', ADDENDUM_SHA, 126)
    ]
    for directory, expected_inventory, expected_count in inventories:
        inventory = directory / 'frozen-output-manifest.json'
        if sha(inventory) != expected_inventory:
            raise ValueError('Frozen inventory changed')
        files = json.loads(inventory.read_text())['files_sha256']
        if len(files) != expected_count:
            raise ValueError('Frozen inventory incomplete')
        for name, expected in files.items():
            bound[(directory / name).relative_to(ROOT).as_posix()] = expected
        for path in [inventory, directory / 'SHA256SUMS']:
            bound[path.relative_to(ROOT).as_posix()] = sha(path)
    addendum = json.loads((CPU / 'post-freeze-review-v1/receipt.json').read_text())
    if addendum['actual_v2_ABI_files'] != 2020 or not addendum['production_source_and_initial_freeze_unchanged']:
        raise ValueError('Actual ABI correction required')
    if sha(CPU / 'source' / SOURCE) != SOURCE_SHA or sha(CPU / 'source/delta-v11-v12.patch') != DELTA_SHA:
        raise ValueError('Reviewed CPU bytes changed')
    summaries = {}
    for kind, total in [('red', 5), ('format', 90), ('sysclk', 48), ('params', 140)]:
        directory = HERE / ('build/root-v12-' + kind + '-v1')
        result = json.loads((directory / 'result.json').read_text())
        invocation = json.loads((directory / 'root-invocation.json').read_text())
        if invocation['exit'] != 0 or not invocation['runner_completed_all_environments'] or invocation['frozen_files_verified'] != 2287:
            raise ValueError('Fresh completed root runner required')
        is_red = kind == 'red'
        source_path = (CPU / 'inputs/outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v11/source' / SOURCE
                       if is_red else CPU / 'source' / SOURCE)
        if result['source_sha256'] != sha(source_path) or result['expected_red'] != is_red:
            raise ValueError('Wrong source/result identity')
        source = source_path.read_text()
        functions = result.get('production_functions_sha256', result.get('cpu_functions_sha256'))
        extracted = (directory / ('actual-functions.c' if kind in ['red', 'format'] else 'actual-cpu-functions.c')).read_text()
        unit = (directory / 'unit.c').read_text()
        for name, expected in functions.items():
            actual_body = body(source, name)
            if hashlib.sha256(actual_body.encode()).hexdigest() != expected or actual_body not in extracted or actual_body not in unit:
                raise ValueError('Actual production body differs: ' + name)
        if set(result['runs']) != {'host', 'asan-ubsan', 'aarch64-qemu'}:
            raise ValueError('Three environments required')
        for label, run in result['runs'].items():
            expected_tests = {'total': total, 'passed': total - int(is_red)}
            if run['tests'] != expected_tests or run['exit'] != int(is_red):
                raise ValueError('Unexpected test outcome')
            expected_failures = ['worker_before_fmt_out_reaches_idle'] if is_red else []
            if run['failures'] != expected_failures or run['expected_red_reproduced'] != is_red:
                raise ValueError('Unexpected failure identity')
            argv = run['compile_argv']
            if str(directory / 'unit.c') not in argv:
                raise ValueError('Fresh unit was not compiled')
            binary = Path(argv[argv.index('-o') + 1])
            for path, expected in [(binary, run['binary_sha256']),
                                   (directory / (label + '.stdout'), run['stdout_sha256']),
                                   (directory / (label + '.stderr'), run['stderr_sha256'])]:
                if sha(path) != expected:
                    raise ValueError('Fresh execution evidence changed')
            if (directory / (label + '.stderr')).read_bytes() or (directory / (label + '-compile.stderr')).read_bytes():
                raise ValueError('Unexpected execution/compiler diagnostic')
        for path in directory.rglob('*'):
            if path.is_file():
                bound[path.relative_to(ROOT).as_posix()] = sha(path)
        runner_copy = directory.with_name(directory.name + '.runner.py')
        if runner_copy.exists():
            bound[runner_copy.relative_to(ROOT).as_posix()] = sha(runner_copy)
        summaries[kind] = {'tests_per_environment': total, 'passed_per_environment': total - int(is_red),
                           'result_sha256': sha(directory / 'result.json'), 'fresh_compilation': True}

    builder = (HERE / 'build-audio-image-v2.py').read_text()
    builder = builder.replace('aiot-3568pq-audio-v2', 'aiot-3568pq-audio-v3')
    builder = replace_once(builder, "output = HERE / 'build/integration-v2'", "output = HERE / 'build/integration-v3'")
    builder = replace_once(builder, "CPU_SHA = '87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c'", "CPU_SHA = '" + SOURCE_SHA + "'")
    builder = replace_once(builder, '    patches += [c3_patch, cpu_patch, cpu_delta]',
                           "    format_delta = HERE / 'cpu-lifecycle-v12/source/delta-v11-v12.patch'\n"
                           "    if gate.get('cpu_v12_independent_review_completed') is not True:\n"
                           "        raise ValueError('CPU v12 independent review required')\n"
                           "    if bound.get(format_delta.relative_to(ROOT).as_posix()) != '" + DELTA_SHA + "':\n"
                           "        raise ValueError('Reviewed CPU v12 delta required')\n"
                           "    patches += [c3_patch, cpu_patch, cpu_delta, format_delta]")
    builder = replace_once(builder, "              'battery_algorithm_enabled': False,",
                           "              'cpu_v12_inventory_sha256': '" + INVENTORY_SHA + "',\n"
                           "              'cpu_v12_addendum_inventory_sha256': '" + ADDENDUM_SHA + "',\n"
                           "              'battery_algorithm_enabled': False,")
    builder_path = HERE / 'build-audio-image-v3.py'
    fresh_write(builder_path, builder)
    codec = (HERE / 'build-integrated-codec-v2.py').read_text()
    codec = codec.replace('aiot-3568pq-audio-v2', 'aiot-3568pq-audio-v3')
    codec = replace_once(codec, "IMAGE = HERE / 'build/integration-v2'", "IMAGE = HERE / 'build/integration-v3'")
    codec = replace_once(codec, "OUT = HERE / 'build/integrated-codec-v2'", "OUT = HERE / 'build/integrated-codec-v3'")
    codec_path = HERE / 'build-integrated-codec-v3.py'
    fresh_write(codec_path, codec)
    for path in [previous_path, Path(__file__), HERE / 'REVIEW-CPU-v12-20261006.md',
                 HERE / 'prepare-audio-v3-source.py', HERE / 'build/source-preparation-v3/result.json',
                 builder_path, codec_path]:
        bound[path.relative_to(ROOT).as_posix()] = sha(path)
    for name, expected in bound.items():
        path = ROOT / name
        if path.is_symlink() or sha(path) != expected:
            raise ValueError('Reviewed binding changed: ' + name)
    gate = {**previous, 'files_sha256': bound,
            'cpu_v12_independent_review_completed': True, 'cpu_v12_root_fresh_execution': summaries,
            'cpu_v12_actual_candidate_ABI_files': 2020,
            'review_mode': 'Independent read-only CPU v12 production/PM caller/freeze review and root fresh red5, format90, shutdown48, params140 in three environments',
            'supersedes': 'review-gate-v3.json', 'new_patch_count': 14,
            'full_image_built': False, 'codec_abi_verified': False, 'board_start_allowed': False,
            'formal_flash_ready': False, 'hardware_operated': False}
    output = HERE / 'build/review-gate-v4.json'
    fresh_write(output, json.dumps(gate, indent=2) + '\n')
    print(json.dumps({'gate_sha256': sha(output), 'bound_files': len(bound),
                      'builder_sha256': sha(builder_path), 'codec_builder_sha256': sha(codec_path)}))


if __name__ == '__main__':
    main()
