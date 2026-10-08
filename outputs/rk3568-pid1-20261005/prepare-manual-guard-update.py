#!/usr/bin/env python3
"""Freeze the guarded RAM-only repair for the production-v2 board experiment."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD_SHA = 'b3cbf88db7d3c335829d857d6dcefc00ca9c848bd9a16db6698835b3eef61b60'
PID_SHA = '8f509bc09988ee419a74b57936bd0c80a0ccf9d214141ebd7b859668a10bc75e'
manifest = json.loads((HERE / 'board-manifest-v3.json').read_text())
assert manifest['artifacts']['pid1']['sha256'] == PID_SHA
assert hashlib.sha256((HERE / 'linux-return-guard.sh').read_bytes()).hexdigest() == manifest['return_guard_sha256']
inspection = HERE / 'pid1-inspect-v3.json'
assert hashlib.sha256(inspection.read_bytes()).hexdigest() == manifest['sessions'][inspection.name]
source = json.loads(inspection.read_text())
rows = [dict(
    command="test -f /tmp/pid1-return-guard.sh && test ! -L /tmp/pid1-return-guard.sh && test \"$(sha256sum /tmp/pid1-return-guard.sh)\" = '" + OLD_SHA + "  /tmp/pid1-return-guard.sh' && echo ORIGINAL_RAM_GUARD_VERIFIED",
    expect=r'(?m)^ORIGINAL_RAM_GUARD_VERIFIED\r?$',
    wait=1,
)]
rows += [row for row in source if row['command'].startswith("printf '%b'")]
rows += [row for row in source if row.get('expect') == r'(?m)^PID1_RETURN_GUARD_SHA_VERIFIED\r?$']
assert len(rows) > 3
assert len(rows[-1:]) == 1 and manifest['return_guard_sha256'] in rows[-1]['command']
assert all(all(32 <= ord(character) <= 126 for character in row['command']) for row in rows)
output = HERE / 'pid1-ram-guard-update-manual-v2.json'
assert not output.exists()
output.write_text(json.dumps(rows, indent=2) + '\n')
print(json.dumps(dict(commands=len(rows), new_guard_sha256=manifest['return_guard_sha256'])))
