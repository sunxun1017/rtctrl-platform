#!/usr/bin/env python3
"""Full property/reservation comparison for the actual fourth RAM trial."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'build/root-live-fdt-v4-audit'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = ROOT / 'outputs/rk3568-boot-package-20261005/dt-semantics-v2.py'
assert sha(parser) == 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56'
spec = importlib.util.spec_from_file_location('locked_parser', parser)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
baseline = HERE / 'build/audio-ram-shim-v1/applied-audit-only.dtb'
previous = HERE / 'build/root-live-fdt-v3-audit/live.dtb'
live = OUT / 'live.dtb'
assert sha(baseline) == '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'
assert sha(previous) == 'c1cf7fd3ea52dc33171d6631f46d587d68fa180737c16c8d22fd0a69a0a3120a'
assert sha(live) == '93dfe8b5bb3dc943b2734a07aaca245c2a0ad503890c5256bc6da22f1879c2a0'
before, prior, after = [module.parse(path.read_bytes()) for path in [baseline, previous, live]]
assert before['nodes'] == after['nodes'] and len(after['nodes']) == 962
assert module.phandles(before) == module.phandles(after) and len(module.phandles(after)) == 762
changes = {key: {'before': before['properties'].get(key), 'after': after['properties'].get(key)}
           for key in sorted(before['properties'].keys() | after['properties'].keys())
           if before['properties'].get(key) != after['properties'].get(key)}
prior_changes = {key: {'before': prior['properties'].get(key), 'after': after['properties'].get(key)}
                 for key in sorted(prior['properties'].keys() | after['properties'].keys())
                 if prior['properties'].get(key) != after['properties'].get(key)}
assert len(changes) == 31 and len(before['properties']) == 4886 and len(after['properties']) == 4915
assert not prior_changes and prior['reservations'] == after['reservations']
assert prior['nodes'] == after['nodes'] and module.phandles(prior) == module.phandles(after)
assert all(key.rsplit(':', 1)[1] not in ['status', 'compatible', 'phandle', 'linux,phandle'] for key in changes)
record = {'baseline_sha256': sha(baseline), 'previous_live_sha256': sha(previous), 'live_sha256': sha(live),
          'parser_sha256': sha(parser), 'tool_sha256': sha(Path(__file__)),
          'nodes': 962, 'phandles': 762, 'before_properties': 4886, 'after_properties': 4915,
          'full_property_changes_from_baseline': changes, 'full_property_changes_from_previous': prior_changes,
          'reservations_before': before['reservations'], 'reservations_after': after['reservations'],
          'full_live_semantics_equal_previous': True, 'independent_review_completed': False,
          'different_whole_file_sha_not_interpreted_as_property_change': True,
          'board_START_granted': False}
with (OUT / 'root-semantic-analysis.json').open('xb') as stream:
    stream.write((json.dumps(record, indent=2) + '\n').encode())
print(json.dumps({'nodes': 962, 'phandles': 762, 'changes_from_baseline': len(changes),
                  'changes_from_previous': len(prior_changes), 'reservations_equal_previous': True}))
