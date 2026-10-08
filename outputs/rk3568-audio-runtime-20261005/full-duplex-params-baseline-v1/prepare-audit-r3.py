#!/usr/bin/env python3
"""Preserve the readback policy assumption failure; do not rerun any C compiler."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = HERE / 'audit-execution-v2.py'
    text = source.read_text()
    changes = {
        "output = HERE / 'execution-readback-v2'": "output = HERE / 'execution-readback-v3'",
        "if '-Wextra' in flags or '-Werror' in flags:": "if '-Wextra' in flags or '-Wsign-compare' in flags:",
        'Prior actual integration-v4 PCM compile command did not enable -Wextra or global -Werror; harness-only -Wno-sign-compare retains other strict checks.':
            'Prior actual integration-v4 C PCM command contains global -Werror but enables neither -Wextra nor -Wsign-compare. Harness -Wextra exposed this comparison; harness-only -Wno-sign-compare retains other strict checks.'}
    for old, new in changes.items():
        if text.count(old) != 1:
            raise ValueError('Expected unique readback correction')
        text = text.replace(old, new)
    target = HERE / 'audit-execution-v3.py'
    if target.exists():
        raise ValueError('Fresh audit version required')
    target.write_text(text)
    observed = HERE / 'execution-readback-v2/failure-observed.json'
    observed.write_text(json.dumps({'status': 'READBACK_ASSUMPTION_FAILURE_OBSERVED_IN_EXEC_TOOL',
        'tool_sha256': sha(source), 'snapshot_sha256': sha(HERE / 'execution-readback-v2/audit-snapshot.py'),
        'reported_exit': 1, 'reason': 'Unexpected prior actual kernel warning policy at original audit line 171',
        'incorrect_assumption': 'No global -Werror in actual kernel .cmd',
        'actual_finite_observation': 'Actual .soc-pcm.o.cmd has global -Werror and no -Wextra/-Wsign-compare',
        'original_stderr_captured_as_file': False, 'C_models_recompiled_or_reexecuted': False}, indent=2) + '\n')
    record = HERE / 'audit-r3-change.json'
    record.write_text(json.dumps({'original_audit_sha256': sha(source), 'new_audit_sha256': sha(target),
        'changes': changes, 'old_failed_evidence': sha(observed),
        'source_model_runner_and_C_execution_unchanged': True}, indent=2) + '\n')
    print(json.dumps({'new_audit_sha256': sha(target), 'change_record_sha256': sha(record),
        'C_models_recompiled_or_reexecuted': False}))


if __name__ == '__main__':
    main()
