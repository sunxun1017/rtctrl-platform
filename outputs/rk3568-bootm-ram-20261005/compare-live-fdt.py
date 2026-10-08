#!/usr/bin/env python3
"""Report every bootloader FDT change; does not authorize unknown changes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--parser-sha256', required=True)
parser.add_argument('base', type=Path)
parser.add_argument('live', type=Path)
parser.add_argument('private_result', type=Path)
args = parser.parse_args()
here = Path(__file__).resolve().parent
source = here.parent / 'rk3568-boot-package-20261005/dt-semantics-v2.py'
if not re.fullmatch('[0-9a-f]{64}', args.parser_sha256):
    raise ValueError('Invalid expected parser hash')
if hashlib.sha256(source.read_bytes()).hexdigest() != args.parser_sha256:
    raise ValueError('Parser differs from reviewed input')
spec = importlib.util.spec_from_file_location('semantics', source)
semantics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(semantics)
base_bytes, live_bytes = args.base.read_bytes(), args.live.read_bytes()
base, live = semantics.parse(base_bytes), semantics.parse(live_bytes)
semantics.phandles(base)
semantics.phandles(live)
bp, lp = base['properties'], live['properties']
changes = {
    key: {'before': bp.get(key), 'after': lp.get(key)}
    for key in sorted(bp.keys() | lp.keys()) if bp.get(key) != lp.get(key)
}
added = sorted(set(live['nodes']) - set(base['nodes']))
removed = sorted(set(base['nodes']) - set(live['nodes']))
metadata = {
    key: {'before': base[key], 'after': live[key]}
    for key in ('reservations', 'boot_cpuid', 'version', 'last_compatible_version')
    if base[key] != live[key]
}
record = {
    'parser_sha256': args.parser_sha256,
    'base_sha256': hashlib.sha256(base_bytes).hexdigest(),
    'live_sha256': hashlib.sha256(live_bytes).hexdigest(),
    'added_nodes': added, 'removed_nodes': removed,
    'property_changes': changes, 'metadata_changes': metadata,
    'semantic_review_completed': False,
}
with args.private_result.open('x') as stream:
    json.dump(record, stream, indent=2)
    stream.write('\n')
# Runtime identifiers remain in the private receipt, not in console summaries.
print(json.dumps({
    'base_sha256': record['base_sha256'], 'live_sha256': record['live_sha256'],
    'added_nodes': added, 'removed_nodes': removed,
    'changed_property_keys': list(changes),
    'changed_metadata_keys': list(metadata), 'semantic_review_completed': False,
}, indent=2))
