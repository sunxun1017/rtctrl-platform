#!/usr/bin/env python3
"""Prepare separate reviewed console observations; never connect or execute them."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / 'build' / 'live-audio-v4'
OUT.mkdir(exist_ok=False)
GUARD = '/tmp/audio/audio-session-guard-v4'
GUARD_SHA = '8740384398313be87a13245e854d6fc5a17a10f3794bdd83966e933c894c6f69'
TRANSFER = '/tmp/audio/pcm-transfer'
TRANSFER_SHA = '2a6c765bd9c3c25b3456e60d68670231e81dcaf7781b827559cd701beed09e2e'
CPU = '/sys/bus/platform/devices/fe410000.i2s'
DMA = '/sys/bus/amba/devices/fe550000.dmac'
CLK = '/tmp/audio-debug/clk'


def save(label, steps):
    for step in steps:
        assert all(32 <= ord(c) <= 126 for c in step['command'])
        assert step.get('wait', 1) <= 60
    (OUT / (label + '.json')).write_bytes(
        (json.dumps(steps, indent=2) + '\n').encode('ascii'))


for label, stage in [
    ('pre-playback-v4', 'bound'), ('post-playback-v4', 'bound'),
    ('pre-capture-v4', 'bound'), ('post-capture-v4', 'bound'),
    ('card-unbound-v4', 'card-unbound'), ('cpu-unbound-v4', 'cpu-unbound'),
]:
    args = f'{stage} 1 {CPU} {DMA}'
    if stage == 'bound':
        args += ' 2 /tmp/audio/alsa-inspect'
    elif stage == 'card-unbound':
        args += ' 2'
    args += ' ' + CLK
    prefix = '/tmp/audio/' + label
    marker = label.upper().replace('-', '_') + '_EXIT_0'
    command = (
        f'if test ! -e {prefix}.stdout && test ! -e {prefix}.stderr && '
        f'test ! -e {prefix}.exit && test "$(sha256sum {GUARD})" = '
        f"'{GUARD_SHA}  {GUARD}'; then "
        f'{GUARD} {args} > {prefix}.stdout 2> {prefix}.stderr; '
        f'guard_rc=$?; printf "%s\\n" "$guard_rc" > {prefix}.exit; '
        f'cat {prefix}.stdout; cat {prefix}.stderr; '
        f'test "$guard_rc" = 0 && echo {marker}; '
        f'else echo AUDIO_FRESH_FILE_OR_IDENTITY_REFUSED; fi')
    save(label, [{'command': command, 'wait': 5,
                  'expect': '(?m)^' + marker + r'\r?$'}])

for stream in ['playback', 'capture']:
    label = stream + '-bounded-v4'
    prefix = '/tmp/audio/' + label
    marker = label.upper().replace('-', '_') + '_EXIT_0'
    command = (
        f'if test ! -e {prefix}.stdout && test ! -e {prefix}.stderr && '
        f'test ! -e {prefix}.exit && test "$(sha256sum {TRANSFER})" = '
        f"'{TRANSFER_SHA}  {TRANSFER}'; then "
        f'{TRANSFER} --card-id rockchiprk809co --stream {stream} '
        f'--frames 24576 --timeout-ms 5000 '
        f'> {prefix}.stdout 2> {prefix}.stderr; '
        f'pcm_rc=$?; printf "%s\\n" "$pcm_rc" > {prefix}.exit; '
        f'cat {prefix}.stdout; cat {prefix}.stderr; '
        f'test "$pcm_rc" = 0 && echo {marker}; '
        f'else echo AUDIO_FRESH_FILE_OR_IDENTITY_REFUSED; fi')
    save(label, [{'command': command, 'wait': 8,
                  'expect': '(?m)^' + marker + r'\r?$'}])

print('Prepared eight separate command files; none executed. Root must inspect each gate before the next action.')
