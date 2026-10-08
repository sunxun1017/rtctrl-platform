#!/usr/bin/env python3
"""Stop only the exact malfunctioning C1 processes launched by finalize tests v1."""
import json
import os
import signal
from pathlib import Path
HERE = Path(__file__).resolve().parent
expected = [
    ['/usr/bin/python3', str(HERE / 'test-pl330-c3-probe.py'), '--source-dir', str(HERE / 'driver-source-c3-v7'), '--label', 'green-v2'],
    [str(HERE / 'pl330-c3-probe-tests-green-v2/pl330-host')],
    [str(HERE / 'pl330-c3-probe-tests-green-v2/pl330-host-sanitized')],
    [str(HERE.parents[1] / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'), str(HERE / 'pl330-c3-probe-tests-green-v2/pl330-aarch64')],
]
matched = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdecimal():
        continue
    try:
        argv = [value.decode() for value in (proc / 'cmdline').read_bytes().split(b'\0') if value]
        if argv not in expected:
            continue
        pid = int(proc.name)
        record = {'pid': pid, 'argv': argv, 'action': 'SIGTERM only this exact task child'}
        os.kill(pid, signal.SIGTERM)
        matched.append(record)
    except (FileNotFoundError, ProcessLookupError):
        pass
result = {'expected_exact_argv': expected, 'terminated': matched}
(HERE / 'finalize-stop-own-c1-v1.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
