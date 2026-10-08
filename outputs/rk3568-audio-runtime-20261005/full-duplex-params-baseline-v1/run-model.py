#!/usr/bin/env python3
"""Run only the old production params baseline after parent source/model review."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4'
IMAGE_INVENTORY = HERE.parent / 'build/integration-v4/integrated-source-inventory.json'
IMAGE_INVENTORY_SHA = 'bb2fb1a0c548bb2de8e683ebd6540f3cb75ddb5815af3df7cf2f8a1d918d0cd3'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ordinary(path):
    if not path.is_relative_to(ROOT) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Ordinary workspace file required')
    ancestor = path.parent
    while ancestor != ROOT:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError('Nonordinary ancestor')
        ancestor = ancestor.parent
    return path


def body(text, name, digest):
    # Keep the old lexical SHA convention when headers split return type/name.
    for pattern in [r'^[A-Za-z_][A-Za-z_0-9 \t*]*\b', r'^[A-Za-z_][A-Za-z_0-9 \t*\n]*\b']:
        for match in re.finditer(pattern + re.escape(name) + r'\([^;{}]*?\)\s*\{', text, re.M):
            depth = 0
            for index in range(text.index('{', match.start()), len(text)):
                depth += (text[index] == '{') - (text[index] == '}')
                if depth == 0:
                    candidate = text[match.start():index + 1]
                    if sha(candidate.encode()) == digest:
                        return candidate
                    break
    raise ValueError('Production body identity mismatch: ' + name)


def check_inputs(model, inputs):
    actual = {p.relative_to(model).as_posix(): sha(ordinary(p).read_bytes()) for p in model.rglob('*') if p.is_file() and p.name != 'input-manifest.json'}
    if actual != inputs['model_files_sha256']:
        raise ValueError('Exact model file set/content changed')
    if sha(ordinary(IMAGE_INVENTORY).read_bytes()) != IMAGE_INVENTORY_SHA:
        raise ValueError('Image source inventory identity changed')
    inventory = json.loads(IMAGE_INVENTORY.read_text())
    mapping = {'cpu': 'sound/soc/rockchip/rockchip_i2s_tdm.c', 'codec': 'sound/soc/codecs/rk817_codec.c',
        'dai': 'sound/soc/soc-dai.c', 'component': 'sound/soc/soc-component.c',
        'simple': 'sound/soc/generic/simple-card-utils.c', 'link': 'sound/soc/soc-link.c',
        'pcm': 'sound/soc/soc-pcm.c', 'soc-header': 'include/sound/soc.h',
        'compress': 'sound/soc/soc-compress.c', 'component-header': 'include/sound/soc-component.h'}
    records = {}
    texts = {}
    for label, rel in mapping.items():
        path = ordinary(SOURCE / rel)
        actual = {'bytes': path.stat().st_size, 'mode': '100755' if path.stat().st_mode & stat.S_IXUSR else '100644', 'sha256': sha(path.read_bytes())}
        if actual != inventory[rel]:
            raise ValueError('Finite actual SOURCE/Image identity changed: ' + rel)
        texts[label] = path.read_text()
        records[rel] = actual
    unit = (model / 'unit.c').read_text()
    extra = (model / 'actual-params-functions.c').read_text()
    for key, digest in inputs['inherited_production_functions_sha256'].items():
        label, name = key.split(':', 1)
        actual = body(texts[label], name, digest)
        if unit.count(actual) != 1:
            raise ValueError('Inherited real body is not byte exact: ' + key)
    rebuilt = []
    for key, digest in inputs['added_production_functions_sha256'].items():
        leaf, name = key.split(':', 1)
        source = (model / 'production-source-inputs' / leaf).read_text()
        actual = body(source, name, digest)
        if extra.count(actual) != 1:
            raise ValueError('Added real body is not byte exact: ' + key)
        rebuilt.append(actual)
    if '\n\n'.join(rebuilt) + '\n' != extra:
        raise ValueError('Additional production unit differs')
    return records


def expected_contracts():
    names = []
    for direction in range(2):
        names += [f'peer_{direction}_CPU_error_preserves_configured_DAI_rate',
            f'peer_{direction}_component_error_preserves_configured_DAI_rate',
            f'two_HW_FREE_then_close_first_{direction}_clears_configuration_cache',
            f'running_peer_{direction}_after_component_error_rejects_before_shared_mutation']
    return names


def observe(text):
    contracts, boundaries, events = [], [], {}
    for line in text.splitlines()[:-1]:
        if line.startswith('CONTRACT_CHECK '):
            name, passed = line.split()[1:]
            contracts.append((name, int(passed)))
        elif line.startswith('BOUNDARY_CHECK '):
            name, passed = line.split()[1:]
            boundaries.append((name, int(passed)))
        elif line.startswith('PARAM_EVENT '):
            _, case, seq, name, value, result = line.split()
            rows = events.setdefault(case, [])
            if int(seq) != len(rows):
                raise ValueError('Transcript sequence gap')
            rows.append({'name': name, 'value': int(value), 'result': int(result)})
        else:
            raise ValueError('Unknown model stdout line')
    final = json.loads(text.splitlines()[-1])
    counts = {'contract_total': len(contracts), 'contract_passed': sum(v for _, v in contracts),
        'boundary_total': len(boundaries), 'boundary_passed': sum(v for _, v in boundaries)}
    if final != counts or any(v not in [0, 1] for _, v in contracts + boundaries):
        raise ValueError('Counts do not match actual assertion rows')
    expected_cases = set()
    for direction in range(2):
        expected_cases |= {f'idle_first_{direction}', f'idle_second_{direction}',
            f'peer_{direction}_CPU_error_preserves_configured_DAI_rate',
            f'peer_{direction}_component_error_preserves_configured_DAI_rate',
            f'two_HW_FREE_then_close_first_{direction}_clears_configuration_cache',
            f'healthy_running_peer_{direction}_same_rate',
            f'running_peer_{direction}_after_component_error_rejects_before_shared_mutation',
            f'single_START_peer_{direction}_after_error_0', f'single_START_peer_{direction}_after_error_1',
            f'refused_second_START_peer_{direction}', f'single_START_CPU_API_error_{direction}'}
    critical = {'actual_first_full_params_order_and_two_DAI_cache',
        'actual_second_idle_same_params_full_chain_success',
        'actual_CPU_failure_excludes_failing_DAI_or_component_failure_clears_both',
        'actual_two_HW_FREE_while_both_still_open',
        'latest_normal_close_balances_refs_and_clears_only_sysclk_requests',
        'healthy_running_same_rate_CPU_sysclk_gate_before_codec_PLL',
        'healthy_running_different_rate_retains_original_symmetry_EINVAL',
        'post_error_different_rate_reaches_real_machine_CCF_then_CPU_sysclk_refusal',
        'actual_single_START_component_DMA_then_DAI_order',
        'actual_second_START_keeps_CPU_component_early_gate_and_no_DMA_GO',
        'actual_C3_START_prefix_and_first_errno_rollback_after_CPU_API_failure',
        'actual_failed_START_transcript_contains_component_DMA_before_CPU_DAI'}
    valid = counts == {'contract_total': 8, 'contract_passed': 0, 'boundary_total': 76, 'boundary_passed': 76}
    valid &= [n for n, v in contracts if not v] == expected_contracts()
    valid &= critical <= {n for n, _ in boundaries} and set(events) == expected_cases
    return {'valid': bool(valid), 'counts': counts, 'business_reds': [n for n, v in contracts if not v],
        'boundary_failures': [n for n, v in boundaries if not v],
        'boundary_names': [n for n, _ in boundaries], 'transcripts': events,
        'unique_boundary_labels': len({n for n, _ in boundaries})}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--check', action='store_true', help='Only read source/model identities; no compiler or model execution')
    args = parser.parse_args()
    if not re.fullmatch(r'model-v[0-9]+', args.model) or not re.fullmatch(r'[a-z0-9]+', args.attempt):
        parser.error('Versioned local model and fresh alphanumeric attempt required')
    model = HERE / args.model
    manifest = ordinary(model / 'input-manifest.json').read_bytes()
    if sha(manifest) != args.manifest_sha256:
        raise ValueError('Reviewed model manifest SHA differs')
    inputs = json.loads(manifest)
    initial = check_inputs(model, inputs)
    if args.check:
        print(json.dumps({'status': 'SOURCE_MODEL_READONLY_PRECHECK', 'actual_SOURCE_finite_files': len(initial),
            'inherited_real_bodies': len(inputs['inherited_production_functions_sha256']),
            'added_real_bodies': len(inputs['added_production_functions_sha256']),
            'model_manifest_sha256': sha(manifest), 'runner_sha256': sha(Path(__file__).read_bytes()),
            'model_executed': False, 'compiler_executed': False}))
        return 0
    output = HERE / ('runs-' + args.attempt)
    output.mkdir(exist_ok=False)
    (output / 'runner-snapshot.py').write_bytes(Path(__file__).read_bytes())
    (output / 'input-manifest.json').write_bytes(manifest)
    receipt = {'status': 'RUNNING', 'runner_sha256': sha(Path(__file__).read_bytes()),
        'model_manifest_sha256': sha(manifest), 'Image_source_inventory_sha256': IMAGE_INVENTORY_SHA,
        'actual_SOURCE_before': initial, 'inherited_real_bodies_available': 70, 'added_real_bodies_available': 20,
        'fixed_counts': {'contract_total': 8, 'contract_passed': 0, 'boundary_total': 76, 'boundary_passed': 76},
        'model_runs': {}, 'production_modified': False, 'Kbuild_executed': False, 'board_tested': False,
        'duplex_START_authorized': False, 'four_prior_duplex_reds_resolved': False,
        'scope': 'Old production caller baseline only. Available body counts are not executed-function coverage. I2C, CCF, DMA/PL330, DAPM, PM, constraints and muted codec callbacks are API models.'}

    def command(argv, name):
        argv = [str(v) for v in argv]
        result = subprocess.run(argv, capture_output=True, timeout=45)
        (output / (name + '.stdout')).write_bytes(result.stdout)
        (output / (name + '.stderr')).write_bytes(result.stderr)
        record = {'argv': argv, 'exit': result.returncode,
            'stdout_sha256': sha(result.stdout), 'stderr_sha256': sha(result.stderr)}
        (output / (name + '.command.json')).write_text(json.dumps(record, indent=2) + '\n')
        return result, record

    failed = False
    for label, compiler, flags, prefix in [
        ('host', 'gcc', [], []),
        ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'], []),
        ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-static'], [ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'])]:
        binary = output / ('params-chain-' + label)
        result, rec = command([compiler, '-std=gnu11', '-O0', '-finstrument-functions', '-Wall', '-Wextra', '-Werror',
            '-Wno-unused-parameter', '-Wno-unused-function', '-pthread', *flags, model / 'unit.c', '-o', binary], label + '-compile')
        record = {'compile': rec}
        if result.returncode:
            failed = True
        else:
            result, rec = command([*prefix, binary], label + '-execute')
            record.update({'execution': rec, 'binary_sha256': sha(binary.read_bytes())})
            try:
                observation = observe(result.stdout.decode())
                valid = observation['valid'] and result.returncode == 1 and not result.stderr
                record['observation'] = observation
            except (ValueError, IndexError) as error:
                valid = False
                record['observation_error'] = str(error)
            record['expected_old_red_scope_verified'] = valid
            failed |= not valid
        receipt['model_runs'][label] = record
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    receipt['actual_SOURCE_after'] = check_inputs(model, inputs)
    if receipt['actual_SOURCE_after'] != initial or sha(Path(__file__).read_bytes()) != receipt['runner_sha256']:
        raise ValueError('Execution input identity changed')
    receipt['status'] = 'HARNESS_OR_UNEXPECTED_FAILURE' if failed else 'OLD_PARAMS_BUSINESS_REDS_REPRODUCED'
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'runs': {k: {'compile_exit': v['compile']['exit'],
        'counts': v.get('observation', {}).get('counts'), 'boundary_failures': v.get('observation', {}).get('boundary_failures')}
        for k, v in receipt['model_runs'].items()}}))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
