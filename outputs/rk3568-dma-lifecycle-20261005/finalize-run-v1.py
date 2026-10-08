#!/usr/bin/env python3
"""Run immutable v7 candidate through author suites or full-series Kbuild objects."""
import argparse
import json
import subprocess
import time
from pathlib import Path
from source_utils import sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CANDIDATE = HERE / 'driver-source-c3-v7'
CPU = ROOT / 'outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['tests', 'production'], required=True)
    args = parser.parse_args()
    out = HERE / ('finalize-' + args.mode + '-v1')
    out.mkdir(exist_ok=False)
    commands = []
    suites = [
        ('test-pl330-c3-probe.py', 'green-v2', []),
        ('test-pl330-c3-hardware.py', 'green-v2', []),
        ('test-pl330-debugfs.py', 'green-v5', []),
        ('test-dma-admission.py', 'green-v5', []),
        ('test-asoc-cpu.py', 'green-v6', ['--cpu-source', str(CPU / 'sound/soc/rockchip/rockchip_i2s_tdm.c')]),
        ('test-dma-pcm-probe.py', 'green-v2', []),
        ('test-core-lifecycle.py', 'green-v3', []),
        ('test-pl330-probe.py', 'green-v2', []),
        ('test-pcm-memory.py', 'green-v2', []),
    ]
    if args.mode == 'tests':
        planned = [(name[:-3], ['/usr/bin/python3', str(HERE / name), '--source-dir', str(CANDIDATE), '--label', label, *extra], 300) for name, label, extra in suites]
    else:
        planned = [('production-v9', ['/usr/bin/python3', str(HERE / 'build-production.py'), '--source-dir', str(CANDIDATE), '--revision', 'v9', '--cpu-dir', str(CPU)], 2400)]
    for stem, argv, deadline in planned:
        print(json.dumps({'starting': stem, 'argv': argv}), flush=True)
        started = time.monotonic()
        stdout_path = out / (stem + '.stdout')
        stderr_path = out / (stem + '.stderr')
        with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            try:
                completed = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=deadline)
                returncode = completed.returncode
                timed_out = False
            except subprocess.TimeoutExpired:
                returncode = None
                timed_out = True
        record = {
            'stem': stem, 'argv': argv, 'returncode': returncode, 'timed_out': timed_out,
            'elapsed_seconds': time.monotonic() - started,
            'stdout_sha256': sha(stdout_path.read_bytes()),
            'stderr_sha256': sha(stderr_path.read_bytes()),
        }
        commands.append(record)
        (out / 'progress.json').write_text(json.dumps(commands, indent=2) + '\n')
        print(json.dumps(record), flush=True)
    result = {
        'candidate': str(CANDIDATE),
        'candidate_manifest_sha256': sha((CANDIDATE / 'manifest.json').read_bytes()),
        'mode': args.mode,
        'passed': all(item['returncode'] == 0 for item in commands),
        'commands': commands,
        'board_tested': False,
        'image_built': False,
    }
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'result': str(out / 'result.json'), 'passed': result['passed']}), flush=True)
    return int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
