#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run exact caller-chain baseline and require explicit business reds, not crashes."""
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
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    if not args.attempt.isalnum():
        parser.error('attempt must be alphanumeric')
    output = HERE / ('runs-' + args.attempt)
    output.mkdir(exist_ok=False)
    if not args.model.startswith('model-v') or not args.model[7:].isdigit():
        parser.error('explicit generated model-vN required')
    model = HERE / args.model
    expected = []
    for direction in range(2):
        for peer in ['idle', 'running']:
            expected += [f'close_{direction}_peer_{peer}_no_diagnostic',
                         f'close_{direction}_peer_{peer}_retains_codec_request']
        expected += [f'sequential_first_{direction}_second_normal_START',
                     f'failed_open_peer_{direction}_rollback_retains_codec_request',
                     f'failed_open_peer_{direction}_rollback_has_only_startup_diagnostic',
                     f'gap_peer_{direction}_failed_startup_balances_both_child_clocks',
                     f'gap_peer_{direction}_failed_startup_unpublishes_CPU_pointer',
                     f'gap_peer_{direction}_full_get_failure_put_owns_its_references']
    expected += ['concurrent_two_normal_START_commit_both',
                 'hypothetical_dual_joint_STOP_reaches_global_proof',
                 'PM_full_get_normal_peer_put_does_not_clobber_rollback_ownership',
                 'PM_partial_failure_recovers_local_prefix_after_peer_clobber',
                 'PM_new_peer_get_does_not_clobber_prior_rollback_ownership']
    receipt = {'schema': 'rk3568-full-duplex-baseline-run-v1',
               'status': 'RUNNING_EXPECTED_RED', 'production_changes': False,
               'board_tested': False, 'duplex_START_authorized': False,
               'complete_kernel_or_hardware_model': False,
               'input_manifest_sha256': sha((model / 'input-manifest.json').read_bytes()),
               'unit_sha256': sha((model / 'unit.c').read_bytes()),
               'runner_sha256': sha(Path(__file__).read_bytes()),
               'expected_business_failures': expected, 'runs': {}}
    (output / 'runner-snapshot.py').write_bytes(Path(__file__).read_bytes())
    (output / 'input-manifest.json').write_bytes((model / 'input-manifest.json').read_bytes())
    receipt['model_directory'] = model.relative_to(HERE).as_posix()
    receipt['model_files_sha256'] = {path.name: sha(path.read_bytes()) for path in model.iterdir() if path.is_file()}
    failed = False

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
        compiled, record = run([compiler, '-std=gnu11', '-O0', '-Wall', '-Wextra', '-Werror',
            '-Wno-unused-parameter', '-Wno-unused-function', '-pthread', *flags,
            model / 'unit.c', '-o', binary], label + '-compile')
        entry = {'compile': record}
        if compiled.returncode:
            failed = True
        else:
            executed, execution = run([*prefix, binary], label)
            text = executed.stdout.decode()
            failures = [line.split()[1] for line in text.splitlines()
                        if line.startswith('CONTRACT_CHECK ') and line.endswith(' 0')]
            boundary_failures = [line.split()[1] for line in text.splitlines()
                                 if line.startswith('BOUNDARY_CHECK ') and line.endswith(' 0')]
            try:
                counts = json.loads(text.splitlines()[-1])
            except (IndexError, ValueError):
                counts = None
            reproduced = executed.returncode == 1 and failures == expected and not boundary_failures and not executed.stderr
            entry.update({'execution': execution, 'counts': counts, 'failures': failures,
                          'boundary_failures': boundary_failures, 'expected_red_reproduced': reproduced,
                          'binary_sha256': sha(binary.read_bytes())})
            failed |= not reproduced
        receipt['runs'][label] = entry
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    receipt['status'] = 'HARNESS_OR_UNEXPECTED_FAILURE' if failed else 'EXPECTED_BUSINESS_RED_REPRODUCED_THREE_ENVIRONMENTS'
    receipt['expected_red_confirmed'] = not failed
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'runs': {k: {'compile_exit': v['compile']['exit'],
          'counts': v.get('counts'), 'boundary_failures': v.get('boundary_failures'),
          'failures': v.get('failures')} for k, v in receipt['runs'].items()}}))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
