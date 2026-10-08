#!/usr/bin/env python3
"""Read back finite actual results, exact ordered assertions and grouped transcripts."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = HERE / 'runs-baselinev2'
MODEL_SHA = '3c17ce462a8e5b64bf0214e7348f2a5189a32c7de12ae815ecd1a120d9a2b362'
RUNNER_SHA = '847337b64763b629432c9c58fbb4d2540ca9fe9b4923be9a5339a9d771ed9b82'
RESULT_SHA = '669a8d1575f8290862dd599802e722bca43978e543a6e2b9883c82e6536a75bf'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def item(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Nonordinary finite evidence input')
    ancestor = path.parent
    while ancestor != ROOT:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError('Nonordinary ancestor')
        ancestor = ancestor.parent
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def expected_rows(direction):
    rows = []
    def boundary(name):
        rows.append(('BOUNDARY_CHECK', name, 1))
    def contract(name):
        rows.append(('CONTRACT_CHECK', name, 0))
    def setup():
        boundary('actual_two_open_with_latest_clean_PM_and_machine')
    setup()
    boundary('actual_first_full_params_order_and_two_DAI_cache')
    boundary('actual_second_idle_same_params_full_chain_success')
    for stage in ['CPU', 'component']:
        setup()
        boundary('peer_configuration_reaches_real_full_params')
        contract(f'peer_{direction}_{stage}_error_preserves_configured_DAI_rate')
        boundary('original_CPU_or_last_component_error_returned')
        boundary('real_error_prefix_retains_peer_open_and_clock_requests')
        boundary('actual_CPU_failure_excludes_failing_DAI_or_component_failure_clears_both')
    setup()
    boundary('two_free_setup_both_actual_params')
    boundary('actual_two_HW_FREE_while_both_still_open')
    contract(f'two_HW_FREE_then_close_first_{direction}_clears_configuration_cache')
    boundary('latest_normal_close_balances_refs_and_clears_only_sysclk_requests')
    for after_error in [False, True]:
        setup()
        boundary('running_setup_actual_peer_params')
        if after_error:
            boundary('running_precondition_real_component_error_clears_rate_without_CPU_sticky')
        boundary('running_peer_produced_by_real_prepare_and_single_START')
        boundary('actual_single_START_component_DMA_then_DAI_order')
        if after_error:
            contract(f'running_peer_{direction}_after_component_error_rejects_before_shared_mutation')
            boundary('post_error_different_rate_reaches_real_machine_CCF_then_CPU_sysclk_refusal')
        else:
            boundary('healthy_running_same_rate_CPU_sysclk_gate_before_codec_PLL')
        boundary('running_attempt_never_enters_codec_CPU_params_or_DMA_and_keeps_single_owner')
        if not after_error:
            boundary('healthy_running_different_rate_retains_original_symmetry_EINVAL')
            boundary('actual_second_START_keeps_CPU_component_early_gate_and_no_DMA_GO')
        boundary('explicit_real_single_STOP_after_running_fixture')
    setup()
    boundary('START_rollback_setup_actual_full_params_and_prepare')
    boundary('actual_C3_START_prefix_and_first_errno_rollback_after_CPU_API_failure')
    boundary('actual_failed_START_transcript_contains_component_DMA_before_CPU_DAI')
    return rows


def expected_groups(direction):
    return [f'idle_first_{direction}', f'idle_second_{1 - direction}',
        f'peer_{direction}_CPU_error_preserves_configured_DAI_rate',
        f'peer_{direction}_component_error_preserves_configured_DAI_rate',
        f'two_HW_FREE_then_close_first_{direction}_clears_configuration_cache',
        f'single_START_peer_{direction}_after_error_0', f'healthy_running_peer_{direction}_same_rate',
        f'refused_second_START_peer_{direction}', f'single_START_peer_{direction}_after_error_1',
        f'running_peer_{direction}_after_component_error_rejects_before_shared_mutation',
        f'single_START_CPU_API_error_{direction}']


def main():
    pins = {HERE / 'run-model-r2.py': RUNNER_SHA,
        HERE / 'model-v2/input-manifest.json': MODEL_SHA, RUNS / 'receipt.json': RESULT_SHA}
    for path, digest in pins.items():
        if item(path)['sha256'] != digest:
            raise ValueError('Submitted execution input/result identity changed')
    receipt = json.loads((RUNS / 'receipt.json').read_text())
    if receipt['status'] != 'OLD_PARAMS_BUSINESS_REDS_REPRODUCED':
        raise ValueError('Unexpected actual result')
    expected = expected_rows(0) + expected_rows(1)
    expected_cases = expected_groups(0) + expected_groups(1)
    if len(expected) != 84 or sum(row[0] == 'BOUNDARY_CHECK' for row in expected) != 76 or len(expected_cases) != 22:
        raise ValueError('Finite expected sequence changed')
    output = HERE / 'execution-readback-v2'
    output.mkdir(exist_ok=False)
    shutil.copy2(Path(__file__), output / 'audit-snapshot.py')
    inputs = json.loads((HERE / 'model-v2/input-manifest.json').read_text())
    if sha(HERE / 'runs-baselinev1/receipt.json') != inputs['r2_harness_correction']['compiler_failure_receipt_sha256']:
        raise ValueError('Original compiler failure record changed')
    if receipt['actual_SOURCE_before'] != receipt['actual_SOURCE_after'] or len(receipt['actual_SOURCE_before']) != 10:
        raise ValueError('Actual runner source mapping changed')
    source = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4'
    for rel, entry in receipt['actual_SOURCE_before'].items():
        path = source / rel
        actual = {'bytes': item(path)['bytes'], 'mode': '100755' if path.stat().st_mode & stat.S_IXUSR else '100644', 'sha256': sha(path)}
        if actual != entry:
            raise ValueError('Actual finite source current identity changed')
    evidence = {}
    original_stdout = None
    for label in ['host', 'asan-ubsan', 'aarch64-qemu']:
        run = receipt['model_runs'][label]
        if run['compile']['exit'] != 0 or run['execution']['exit'] != 1:
            raise ValueError('Expected real compile0/business-red run1')
        for stage, prefix in [('compile', label + '-compile'), ('execution', label + '-execute')]:
            command_path = RUNS / (prefix + '.command.json')
            if json.loads(command_path.read_text()) != run[stage]:
                raise ValueError('Recorded actual command differs')
            for stream in ['stdout', 'stderr']:
                path = RUNS / (prefix + '.' + stream)
                if item(path)['sha256'] != run[stage][stream + '_sha256']:
                    raise ValueError('Actual stream identity differs')
            if (RUNS / (prefix + '.stderr')).read_bytes():
                raise ValueError('Actual compiler/execution stderr nonempty')
        path = RUNS / ('params-chain-' + label)
        if item(path)['sha256'] != run['binary_sha256']:
            raise ValueError('Actual binary changed')
        stdout_path = RUNS / (label + '-execute.stdout')
        raw = stdout_path.read_bytes()
        if original_stdout is None:
            original_stdout = raw
        elif raw != original_stdout:
            raise ValueError('Three complete stdout byte sequences differ')
        rows, cases, transcripts = [], [], {}
        for line in raw.decode().splitlines()[:-1]:
            if line.startswith(('BOUNDARY_CHECK ', 'CONTRACT_CHECK ')):
                kind, name, result = line.split()
                rows.append((kind, name, int(result)))
            elif line.startswith('PARAM_EVENT '):
                _, case, seq, name, value, result = line.split()
                if case not in transcripts:
                    cases.append(case)
                    transcripts[case] = []
                if int(seq) != len(transcripts[case]):
                    raise ValueError('Transcript sequence gap')
                transcripts[case].append({'name': name, 'value': int(value), 'result': int(result)})
            else:
                raise ValueError('Unknown stdout line')
        if rows != expected or cases != expected_cases or transcripts != run['observation']['transcripts']:
            raise ValueError('Full ordered assertion/case/transcript mismatch')
        if json.loads(raw.decode().splitlines()[-1]) != {'contract_total': 8, 'contract_passed': 0, 'boundary_total': 76, 'boundary_passed': 76}:
            raise ValueError('Actual fixed counts changed')
        evidence[label] = {'stdout': item(stdout_path), 'binary': item(path),
            'actual_argv_exit_streams': {'compile': run['compile'], 'execution': run['execution']},
            'full_76_boundary_labels_order_verified': True, 'full_8_business_red_labels_order_verified': True,
            'full_22_case_group_order_verified': True, 'transcript_entries': sum(len(v) for v in transcripts.values())}
    # Narrow warning-policy evidence: read one prior real kernel .cmd, no build.
    kernel_cmd = ROOT / '.deps/kernel/aiot-3568pq-audio-v4/sound/soc/.soc-pcm.o.cmd'
    command_line = kernel_cmd.read_text().splitlines()[0]
    flags = re.findall(r'(?<!\S)-W[^\s]+', command_line)
    if '-Wextra' in flags or '-Werror' in flags:
        raise ValueError('Unexpected prior actual kernel warning policy')
    warning = {'actual_previous_kernel_cmd': item(kernel_cmd), 'warning_flags': flags,
        'kernel_build_reexecuted': False,
        'scope': 'Prior actual integration-v4 PCM compile command did not enable -Wextra or global -Werror; harness-only -Wno-sign-compare retains other strict checks.'}
    record = {'status': 'ACTUAL_OLD_PARAMS_REDS_AND_ORDERED_OBSERVATIONS_READBACK',
        'runner_r2': item(HERE / 'run-model-r2.py'), 'model_manifest_v2': item(HERE / 'model-v2/input-manifest.json'),
        'actual_runner_receipt': item(RUNS / 'receipt.json'), 'original_compiler_failure_receipt': item(HERE / 'runs-baselinev1/receipt.json'),
        'runner_actual_SOURCE_before_after_count': 10, 'separate_preparation_snapshot_count': 14,
        'available_real_bodies': {'inherited': 70, 'added': 20, 'executed_function_coverage_claimed': False},
        'actual_counts_each_environment': {'contract_total': 8, 'contract_passed': 0, 'boundary_total': 76, 'boundary_passed': 76},
        'ordered_assertions': expected, 'ordered_case_groups': expected_cases,
        'boundary_unique_label_count': len({row[1] for row in expected if row[0] == 'BOUNDARY_CHECK'}),
        'three_complete_stdout_bytes_equal': True, 'environments': evidence, 'warning_policy_evidence': warning,
        'production_modified': False, 'Kbuild_executed': False, 'board_tested': False,
        'duplex_START_authorized': False, 'four_prior_duplex_reds_resolved': False,
        'audit_tool_sha256': sha(Path(__file__))}
    path = output / 'receipt.json'
    path.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'status': record['status'], 'receipt_sha256': sha(path),
        'actual_result_sha256': RESULT_SHA, 'three_stdout_sha256': sha(RUNS / 'host-execute.stdout'),
        'boundary_unique_labels': record['boundary_unique_label_count'], 'ordered_case_groups': len(expected_cases)}))


if __name__ == '__main__':
    main()
