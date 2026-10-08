#!/usr/bin/env python3
"""Run actual Linux test CLI and retain exact invocation/output/exit receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('fixture', 'production'), required=True)
    args = parser.parse_args()
    name = 'fixture-regression-v3' if args.phase == 'fixture' else 'production-inputs-v3'
    script = 'test-audio-package-v3.py' if args.phase == 'fixture' else 'test-production-inputs-v3.py'
    out = HERE / 'build' / (args.phase + '-tests-cli-v3')
    out.mkdir(parents=True, exist_ok=False)
    argv = [sys.executable, '-B', str(HERE / script), '--out', str(HERE / 'build' / name)]
    started = time.monotonic()
    process = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=1200)
    for suffix, data in [('stdout', process.stdout), ('stderr', process.stderr)]:
        (out / suffix).write_bytes(data)
    result = {'argv': argv, 'exit': process.returncode, 'elapsed_seconds': round(time.monotonic() - started, 6),
              'test_source_sha256': hashlib.sha256((HERE / script).read_bytes()).hexdigest(),
              'core_source_sha256': hashlib.sha256((HERE / 'audio-package-v3.py').read_bytes()).hexdigest(),
              'stdout_sha256': hashlib.sha256(process.stdout).hexdigest(),
              'stderr_sha256': hashlib.sha256(process.stderr).hexdigest()}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(process.stdout.decode('utf-8', 'replace'))
    print(process.stderr.decode('utf-8', 'replace'))
    print(json.dumps(result, indent=2))
    raise SystemExit(process.returncode)


if __name__ == '__main__':
    main()
