#!/usr/bin/env python3
"""Check finite checked-profile absence conditions and DMA provider identity."""
from pathlib import Path
import importlib.util
import json
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'build/ram-aux-v3'
spec = importlib.util.spec_from_file_location('dt', ROOT / 'outputs/rk3568-boot-package-20261005/dt-semantics-v2.py')
dt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dt)
props = dt.parse((HERE / 'build/audio-ram-shim-v1/applied-audit-only.dtb').read_bytes())['properties']
steps = []
absent = {'/i2s@fe410000': ['rockchip,bclk-fs', 'rockchip,always-on', 'rockchip,hdmi-path', 'rockchip,mclk-calibrate',
           'rockchip,io-multiplex', 'rockchip,tdm-multi-lanes', 'rockchip,no-dmaengine', 'rockchip,digital-loopback',
           'rockchip,i2s-tx-route', 'rockchip,i2s-rx-route'],
          '/i2c@fdd40000/pmic@20/codec': ['pdmdata-out-enable', 'use-ext-amplifier'],
          '/dmac@fe550000': ['status']}
fmt = ['bitclock-master', 'frame-master', 'bitclock-inversion', 'frame-inversion', 'continuous-clock',
       'dai-tdm-slot-num', 'dai-tdm-slot-width', 'dai-tdm-slot-tx-mask', 'dai-tdm-slot-rx-mask']
for node in ['/rk809-sound', '/rk809-sound/simple-audio-card,cpu', '/rk809-sound/simple-audio-card,codec']:
    absent[node] = fmt + ['simple-audio-card,' + name for name in fmt]
for node, names in absent.items():
    for prop in names:
        assert node + ':' + prop not in props
        path = '/proc/device-tree' + node + '/' + prop
        steps.append({'command': 'test ! -e ' + path + ' && test ! -L ' + path + ' && echo AUDIO_DT_EXPECTED_ABSENT',
                      'wait': 0.1, 'expect': r'(?m)^AUDIO_DT_EXPECTED_ABSENT\r?$'})
for key, value in sorted(props.items()):
    node, prop = key.rsplit(':', 1)
    if node != '/dmac@fe550000' or prop in ('compatible', 'phandle'):
        continue
    path = '/proc/device-tree' + node + '/' + prop
    if value:
        command = '''test -f ''' + path + ''' && printf '%s\\n' "$(hexdump -v -e '1/1 "%02x"' ''' + path + ''')"'''
        expect = r'(?m)^' + value + r'\r?$'
    else:
        command = 'test -f ' + path + ' && test "$(stat -c %s ' + path + ')" = 0 && echo AUDIO_DMA_BOOLEAN_PRESENT'
        expect = r'(?m)^AUDIO_DMA_BOOLEAN_PRESENT\r?$'
    steps.append({'command': command, 'wait': 0.3, 'expect': expect})
target = OUT / 'live-absent-v1.json'
assert not target.exists()
target.write_bytes((json.dumps(steps, indent=2) + '\n').encode())
print(json.dumps({'commands': len(steps), 'full_live_export': False}))
