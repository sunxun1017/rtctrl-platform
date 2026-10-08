#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compare preserved decode and re-encode diagnostics after input-path normalization."""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    source, out = Path(args.build), Path(args.out).absolute()
    if out != out.resolve() or not out.is_relative_to(HERE / 'build'):
        raise ValueError('Own fresh ordinary output required')
    manifest = json.loads((source / 'manifest.json').read_text())
    normalized = {}
    records = []
    for run in manifest['dtc_runs']:
        stem = source / 'dtc' / run['stage']
        stdout, stderr = stem.with_suffix('.stdout').read_bytes(), stem.with_suffix('.stderr').read_bytes()
        if sha(stdout) != run['stdout_sha256'] or sha(stderr) != run['stderr_sha256'] or run['exit_code'] != 0:
            raise ValueError('Preserved DTC output mismatch')
        warnings = stderr.replace(run['argv'][-1].encode(), b'<input>')
        normalized[run['stage']] = warnings
        records.append({'stage': run['stage'], 'raw_warning_bytes': len(stderr),
                        'normalized_warning_bytes': len(warnings), 'normalized_sha256': sha(warnings)})
    for stage in ('decode', 'encode'):
        if normalized['baseline-' + stage] != normalized['candidate-' + stage]:
            raise ValueError('DTC diagnostic changed after normalizing source file path: ' + stage)
    out.mkdir(parents=True, exist_ok=False)
    report = {'decode_diagnostics_same': True, 'encode_diagnostics_same': True,
              'new_dtc_diagnostics': 0, 'records': records,
              'script_sha256': sha(Path(__file__).read_bytes()),
              'manifest_sha256': sha((source / 'manifest.json').read_bytes()),
              'board_tested': False, 'warnings_are_not_dt_binding_validation': True}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'decode_same': True, 'encode_same': True, 'new_dtc_diagnostics': 0}))


if __name__ == '__main__':
    main()
