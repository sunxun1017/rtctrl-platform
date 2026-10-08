#!/usr/bin/env python3
"""Save the independent v17 register-model observation; no board access."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
DMA = HERE.parent / 'rk3568-dma-lifecycle-20261005'
ELF = DMA / 'pl330-hw-tests-green-v6/hardware-host-sanitized'
SOURCE = DMA / 'driver-source-v17/drivers/dma/pl330.c'
EXPECTED = {
    ELF: '5251c47da93fcc07b6ea0b1b27328cc1bb73d6fce0dd24c3b90c8691bc03e522',
    SOURCE: '9985d8f7f02ba12d4acf79f0cdc1c2105058946e7d6a82e662079758a8aef128',
}
for path, sha in EXPECTED.items():
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError('Frozen reviewer input changed: ' + str(path))
out = HERE / 'build/dma-v17-independent-register-review'
out.mkdir(parents=True, exist_ok=False)
records = {}
for label, state in (('WFE', 4), ('INVALID', 10)):
    args = ['gdb', '-nx', '-nh', '-batch']
    for command in (
        'set debuginfod enabled off', 'set history save off',
        'set environment ASAN_OPTIONS detect_leaks=0:disable_coredump=1',
        'break main', 'run', 'call init()', f'set registers[64] = {state}',
        'print guarded(1)', 'print dmac.lifecycle_error', 'print go_commands',
        'print thread.req_running', 'quit',
    ):
        args.extend(('-ex', command))
    args.append(str(ELF))
    result = subprocess.run(args, capture_output=True, timeout=60)
    (out / (label + '.stdout')).write_bytes(result.stdout)
    (out / (label + '.stderr')).write_bytes(result.stderr)
    observed = [int(value) for value in re.findall(rb'^\$[1-4] = (-?\d+)$', result.stdout, re.M)]
    records[label] = {
        'argv': args, 'returncode': result.returncode, 'observed': observed,
        'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
        'stderr_sha256': hashlib.sha256(result.stderr).hexdigest(),
        'reported_gap_reproduced': result.returncode == 0 and not result.stderr and observed == [-5, 0, 0, -1],
    }
receipt = {
    'input_sha256': {str(p.relative_to(HERE.parent)): sha for p, sha in EXPECTED.items()},
    'runs': records, 'board_access': False,
    'scope': 'Register model reaches real _start; caller return handling confirmed separately in real source',
}
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({label: entry['reported_gap_reproduced'] for label, entry in records.items()}))
if not all(entry['reported_gap_reproduced'] for entry in records.values()):
    raise SystemExit(1)
