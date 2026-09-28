"""One-shot provenance tool: rewrite selected captured board nodes with symbols.
Does not translate SoC register/clock definitions or infer missing hardware.
"""
import json
from pathlib import Path
import struct

root = Path(__file__).resolve().parent / 'live-tree'
dest = Path(__file__).resolve().parents[2] / 'platforms/rk3568/boards/aiot-3568pq/bsp'
symbols = {p.name: p.read_bytes().rstrip(b'\0').decode() for p in (root/'__symbols__').iterdir()}
labels = {v: k for k, v in symbols.items()}
handles = {}
for p in root.rglob('phandle'):
    path = '/' + str(p.parent.relative_to(root))
    handles[struct.unpack('>I', p.read_bytes())[0]] = labels.get(path, '')

def ref(value):
    label = handles[value]
    if not label:
        raise ValueError(f'No symbol for phandle {value:#x}')
    return '&' + label

def prop(p):
    data = p.read_bytes()
    name = p.name
    if not data:
        return name + ';'
    if data.rstrip(b'\0') and data.endswith(b'\0') and all(c in (0, 9, 10) or 32 <= c < 127 for c in data):
        return name + ' = ' + ', '.join(json.dumps(v.decode()) for v in data[:-1].split(b'\0')) + ';'
    if len(data) % 4:
        raise ValueError(f'Unclassified byte property: {p}')
    cells = list(struct.unpack('>'+'I'*(len(data)//4), data))
    out = [str(v) for v in cells]
    if name.endswith('-supply') or name == 'interrupt-parent' or name.startswith('pinctrl-') and name != 'pinctrl-names':
        out = [ref(v) for v in cells]
    elif name == 'rockchip,pins':
        for i in range(3, len(cells), 4):
            out[i] = ref(cells[i])
    return name + ' = <' + ' '.join(out) + '>;'

def node(path, level=1, exclude=()):
    directory = root / path.lstrip('/')
    prefix = '    '*level
    label = labels.get(path)
    lines = [prefix + (label+': ' if label else '') + directory.name + ' {']
    for p in sorted(directory.iterdir(), key=lambda p: (p.is_dir(), p.name)):
        if p.name in ('phandle', 'linux,phandle', 'name') or p.name in exclude:
            continue
        if p.is_dir():
            lines += node(path+'/'+p.name, level+1)
        else:
            lines.append(prefix+'    '+prop(p))
    return lines+[prefix+'};']

lines = ['// SPDX-License-Identifier: (GPL-2.0+ OR MIT)',
         '/* Board values reconstructed from Android FDT a028987f...de4dd28b.',
         ' * Labels resolve against Linux 5.10.160 rk3568.dtsi; no EVB carrier include.',
         ' * regulator-init-microvolt is retained as evidence, not a guaranteed',
         ' * startup voltage: the target FAN53555/RK808 drivers do not consume it.',
         ' */', '', '/ {']
for path in ['/dc-12v', '/vcc3v3-sys', '/vcc5v0-sys', '/vcc5v0-usb', '/vcc5v0-host-regulator', '/vcc2v5-ddr']:
    lines += node(path)+['']
lines += ['};', '', '&i2c0 {', '    status = "okay";', '']
lines += node('/i2c@fdd40000/tcs4525@1c')+['']
lines += node('/i2c@fdd40000/pmic@20', exclude=('codec', 'battery', 'charger'))
lines += ['};', '', '&pinctrl {'] + node('/pinctrl/pmic') + ['};', '', '&pmu_io_domains {']
for p in sorted((root/'syscon@fdc20000/io-domains').iterdir()):
    if p.is_file() and (p.name.endswith('-supply') or p.name == 'status'):
        lines.append('    '+prop(p))
lines += ['};', '', '&cpu0 {', '    cpu-supply = <&vdd_cpu>;', '};', '']
dest.mkdir(parents=True, exist_ok=True)
(dest/'rk3568-aiot-3568pq-power.dtsi').write_text('\n'.join(lines))
print('Wrote board power fragment from captured properties')
