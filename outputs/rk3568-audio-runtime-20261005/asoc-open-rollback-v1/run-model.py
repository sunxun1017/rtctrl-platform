#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute extracted callers; green deliberately retains four full-duplex reds."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    if '/' in args.model or '\\' in args.model or not args.attempt.isalnum():
        parser.error('local model and fresh alphanumeric attempt required')
    model = HERE / args.model
    inputs = json.loads((model / 'input-manifest.json').read_text())
    candidate = inputs['mode'] == 'green'
    output = HERE / ('runs-' + args.attempt)
    output.mkdir(exist_ok=False)
    expected = []
    for direction in range(2):
        for peer in ['idle', 'running']:
            expected += [f'close_{direction}_peer_{peer}_no_diagnostic', f'close_{direction}_peer_{peer}_retains_codec_request']
        expected += [f'sequential_first_{direction}_second_normal_START',
                     f'failed_open_peer_{direction}_rollback_retains_codec_request',
                     f'failed_open_peer_{direction}_rollback_has_only_startup_diagnostic',
                     f'gap_peer_{direction}_failed_startup_balances_both_child_clocks',
                     f'gap_peer_{direction}_failed_startup_unpublishes_CPU_pointer',
                     f'gap_peer_{direction}_full_get_failure_put_owns_its_references']
    expected += ['concurrent_two_normal_START_commit_both', 'hypothetical_dual_joint_STOP_reaches_global_proof',
                 'PM_full_get_normal_peer_put_does_not_clobber_rollback_ownership',
                 'PM_partial_failure_recovers_local_prefix_after_peer_clobber',
                 'PM_new_peer_get_does_not_clobber_prior_rollback_ownership']
    if candidate:
        expected = [f'sequential_first_{direction}_second_normal_START' for direction in range(2)] + [
            'concurrent_two_normal_START_commit_both', 'hypothetical_dual_joint_STOP_reaches_global_proof']
    receipt = {'status': 'RUNNING', 'model': args.model, 'candidate': candidate,
               'input_manifest_sha256': sha((model / 'input-manifest.json').read_bytes()),
               'production_functions_sha256': inputs['production_functions_sha256'],
               'runner_sha256': sha(Path(__file__).read_bytes()),
               'model_files_sha256': {path.name: sha(path.read_bytes()) for path in model.iterdir() if path.is_file()},
               'expected_remaining_failures': expected, 'board_tested': False,
               'full_duplex_passed': False, 'duplex_START_authorized': False,
               'trace_method': 'GCC -finstrument-functions observes real full PM put and clean entry without editing function bodies; kernel API scheduling remains modelled',
               'runs': {}}
    receipt['fixed_counts'] = {'contract_total': 25, 'contract_passed': 21 if candidate else 0,
                              'boundary_total': 110, 'boundary_passed': 110}
    (output / 'runner-snapshot.py').write_bytes(Path(__file__).read_bytes())
    (output / 'input-manifest.json').write_bytes((model / 'input-manifest.json').read_bytes())
    failure = False

    def run(argv, stem):
        result = subprocess.run([str(v) for v in argv], capture_output=True, timeout=45)
        (output / (stem + '.stdout')).write_bytes(result.stdout)
        (output / (stem + '.stderr')).write_bytes(result.stderr)
        return result, {'argv': [str(v) for v in argv], 'exit': result.returncode,
                        'stdout_sha256': sha(result.stdout), 'stderr_sha256': sha(result.stderr)}

    for label, compiler, flags, prefix in [
        ('host', 'gcc', [], []),
        ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'], []),
        ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-static'], [ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'])]:
        binary = output / ('caller-chain-' + label)
        compiled, rec = run([compiler, '-std=gnu11', '-O0', '-finstrument-functions', '-Wall', '-Wextra', '-Werror',
            '-Wno-unused-parameter', '-Wno-unused-function', '-pthread', *flags, model / 'unit.c', '-o', binary], label + '-compile')
        record = {'compile': rec}
        if compiled.returncode:
            failure = True
        else:
            executed, rec = run([*prefix, binary], label)
            text = executed.stdout.decode()
            red = [line.split()[1] for line in text.splitlines() if line.startswith('CONTRACT_CHECK ') and line.endswith(' 0')]
            bad = [line.split()[1] for line in text.splitlines() if line.startswith('BOUNDARY_CHECK ') and line.endswith(' 0')]
            try:
                counts = json.loads(text.splitlines()[-1])
            except (IndexError, ValueError):
                counts = None
            contract_rows = [line.split() for line in text.splitlines() if line.startswith('CONTRACT_CHECK ')]
            boundary_rows = [line.split() for line in text.splitlines() if line.startswith('BOUNDARY_CHECK ')]
            line_counts = {'contract_total': len(contract_rows), 'contract_passed': sum(int(row[2]) for row in contract_rows),
                           'boundary_total': len(boundary_rows), 'boundary_passed': sum(int(row[2]) for row in boundary_rows)}
            critical = {f'actual_startup_prefix_{i}_resources_returned_original_errno' for i in range(11)}
            critical |= {f'actual_PCM_get_fail_{i}_no_started_resources_or_double_put' for i in range(3)}
            critical |= {f'actual_compressed_get_fail_{i}_no_startup_or_double_put' for i in range(3)}
            critical |= {'actual_PCM_same_device_EACCES_positive_prefix_and_failed_current_each_once',
                         'actual_compressed_same_device_prefix_failure_no_full_put',
                         'CPU_sticky_zero_gate_remains_rejected_at_last_owner', 'CPU_unproved_IRQ_zero_gate_remains_rejected'}
            names = {row[1] for row in boundary_rows}
            valid = executed.returncode == 1 and red == expected and not bad and not executed.stderr and counts == line_counts == receipt['fixed_counts'] and critical <= names
            record.update({'execution': rec, 'counts': counts, 'remaining_failures': red, 'boundary_failures': bad,
                           'expected_scope_verified': valid, 'binary_sha256': sha(binary.read_bytes())})
            record.update({'line_counts': line_counts, 'critical_boundary_names_present': critical <= names,
                           'boundary_names': [row[1] for row in boundary_rows]})
            failure |= not valid
        receipt['runs'][label] = record
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    receipt['status'] = 'UNEXPECTED_OR_HARNESS_FAILURE' if failure else ('LIMITED_FIX_VERIFIED_FOUR_DUPLEX_REDS_REMAIN' if candidate else 'ORIGINAL_BUSINESS_RED_REPRODUCED')
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'runs': {k: {'compile_exit': v['compile']['exit'],
        'counts': v.get('counts'), 'boundary_failures': v.get('boundary_failures'), 'remaining': v.get('remaining_failures')} for k, v in receipt['runs'].items()}}))
    return int(failure)


if __name__ == '__main__':
    raise SystemExit(main())
