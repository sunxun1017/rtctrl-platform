#!/usr/bin/env python3
"""Record the full live FDT comparison after the independent read-only review."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'build/root-live-fdt-v3-audit'
parser = ROOT / 'outputs/rk3568-boot-package-20261005/dt-semantics-v2.py'
assert hashlib.sha256(parser.read_bytes()).hexdigest() == 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56'
spec = importlib.util.spec_from_file_location('reviewed_fdt_parser', parser)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
baseline = HERE / 'build/audio-ram-shim-v1/applied-audit-only.dtb'
live = OUT / 'live.dtb'
assert hashlib.sha256(baseline.read_bytes()).hexdigest() == '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'
assert hashlib.sha256(live.read_bytes()).hexdigest() == 'c1cf7fd3ea52dc33171d6631f46d587d68fa180737c16c8d22fd0a69a0a3120a'
before, after = module.parse(baseline.read_bytes()), module.parse(live.read_bytes())
assert before['nodes'] == after['nodes'] and len(after['nodes']) == 962
assert module.phandles(before) == module.phandles(after) and len(module.phandles(after)) == 762
changes = {key: {'before': before['properties'].get(key), 'after': after['properties'].get(key)}
           for key in sorted(before['properties'].keys() | after['properties'].keys())
           if before['properties'].get(key) != after['properties'].get(key)}
assert len(changes) == 31
assert len(before['properties']) == 4886 and len(after['properties']) == 4915
assert all(key.rsplit(':', 1)[1] not in ['status', 'compatible', 'phandle', 'linux,phandle'] for key in changes)
record = {
    'baseline_sha256': hashlib.sha256(baseline.read_bytes()).hexdigest(),
    'live_sha256': hashlib.sha256(live.read_bytes()).hexdigest(),
    'parser_sha256': hashlib.sha256(parser.read_bytes()).hexdigest(),
    'nodes': 962, 'phandles': 762, 'before_properties': 4886, 'after_properties': 4915,
    'full_property_changes': changes,
    'reservations_before': before['reservations'], 'reservations_after': after['reservations'],
    'independent_review': {
        'audio_I2S_codec_DMA_clock_reset_power_pinctrl_properties': 'all unchanged',
        'USB_OTG_DRD': 'disabled unchanged; existing USB2 host configuration remains',
        'battery_charger_BQ_FUSB_nodes': 'not introduced',
        'emmc_bridge_and_usb_device_candidates': 'not integrated',
        'display': 'remains disabled; added logo/plane handoff metadata only',
        'memory': 'three nonzero banks unchanged, nine zero tuples appended; OF skips size-zero entries',
        'fdt_memory': 'header reserve grows 0x25000 to 0x29000; arm64 additionally reserves full fdt_totalsize 0x29080',
        'initrd': '[0x4000000,0x40ed5ab), 972203 bytes, matches native3 artifact',
        'scope': 'No DT blocker for the limited PCM trial; does not grant START or replace fresh guard',
        'custom_uboot_fixup_symbols': 'not all individually reverse-engineered',
    },
    'initial_full_dump_rejected': '219 hex characters missing; no inference or zero padding',
    'chunk_22_rejected_and_recollected': '8022 instead of 8192 hex; replaced with 8 exact fresh 512-byte parts',
}
with (OUT / 'semantic-review.json').open('xb') as stream:
    stream.write((json.dumps(record, indent=2) + '\n').encode())
print(json.dumps({'nodes': 962, 'phandles': 762, 'changes': list(changes), 'full_live_sha_matched': True}))
