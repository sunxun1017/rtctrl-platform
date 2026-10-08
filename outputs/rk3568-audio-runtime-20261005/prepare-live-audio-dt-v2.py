#!/usr/bin/env python3
"""Explicit related live-property checks; not a full live FDT export."""
from pathlib import Path
import importlib.util
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('dt', ROOT / 'outputs/rk3568-boot-package-20261005/dt-semantics-v2.py')
dt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dt)
tree = dt.parse((HERE / 'build/audio-ram-shim-v1/applied-audit-only.dtb').read_bytes())
nodes = ['/i2s@fe410000', '/rk809-sound', '/rk809-sound/simple-audio-card,cpu',
         '/rk809-sound/simple-audio-card,codec', '/i2c@fdd40000/pmic@20/codec']
others = ['/i2s@fe400000', '/i2s@fe420000', '/i2s@fe430000', '/pdm@fe440000',
          '/spdif@fe460000', '/audpwm@fe470000', '/serial@fdd50000', '/dmac@fe550000']
checks = {}
for key, value in tree['properties'].items():
    node, prop = key.rsplit(':', 1)
    if node in nodes or (node in others and prop in ('status', 'dmas', 'dma-names', 'compatible', 'phandle')):
        checks[key] = value
assert '/i2c@fdd40000/pmic@20/codec:phandle' in checks
assert checks['/i2s@fe410000:rockchip,clk-trcm'] == '00000001'
steps = []
for key, value in sorted(checks.items()):
    node, prop = key.rsplit(':', 1)
    path = '/proc/device-tree' + node + '/' + prop
    steps.append({'command': '''printf '%s\\n' "$(hexdump -v -e '1/1 "%02x"' ''' + path + ''')"''',
                  'wait': 0.3, 'expect': r'(?m)^' + value + r'\r?$'})
out = HERE / 'build/ram-aux-v3'
(out / 'live-dt-v2.json').write_bytes((json.dumps(steps, indent=2) + '\n').encode())
(out / 'live-dt-v2-expected.json').write_bytes((json.dumps(checks, indent=2) + '\n').encode())
print(json.dumps({'properties': len(checks), 'full_live_tree_export': False}))
