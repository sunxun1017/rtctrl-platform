"""Compare candidate board power values/references with the captured raw FDT."""
import importlib.util
import json
from pathlib import Path
import struct
import sys

repo = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('audit', repo/'platforms/rk3568/boards/aiot-3568pq/verify-firstboot.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original, _ = module.read_dtb(repo/'outputs/android-board-20260928/fdt.dtb')
candidate, _ = module.read_dtb(Path(sys.argv[1]))

def refs(props):
    labels = {v.rstrip(b'\0').decode(): k.removeprefix('/__symbols__/')
              for k, v in props.items() if k.startswith('/__symbols__/')}
    return {struct.unpack('>I', v)[0]: labels[k.rsplit('/', 1)[0]]
            for k, v in props.items() if k.endswith('/phandle') and k.rsplit('/', 1)[0] in labels}

orig_refs, new_refs = refs(original), refs(candidate)

def value(name, blob, handles):
    if name.endswith('-supply') or name == 'interrupt-parent' or name.startswith('pinctrl-') and name != 'pinctrl-names':
        return [handles[v] for v in struct.unpack('>'+'I'*(len(blob)//4), blob)]
    if name == 'rockchip,pins':
        result = list(struct.unpack('>'+'I'*(len(blob)//4), blob))
        for i in range(3, len(result), 4):
            result[i] = handles[result[i]]
        return result
    return blob

prefixes = ['/dc-12v/', '/vcc3v3-sys/', '/vcc5v0-sys/', '/vcc5v0-usb/',
            '/vcc5v0-host-regulator/', '/vcc2v5-ddr/', '/i2c@fdd40000/tcs4525@1c/',
            '/i2c@fdd40000/pmic@20/']
prefixes += ['/pinctrl/pmic/'+name+'/' for name in
             ['pmic_int', 'soc_slppin_gpio', 'soc_slppin_slp', 'soc_slppin_rst']]
compared = []
for path, blob in candidate.items():
    name = path.rsplit('/', 1)[1]
    if name in ('phandle', 'linux,phandle') or not any(path.startswith(p) for p in prefixes):
        continue
    if path not in original or value(name, blob, new_refs) != value(name, original[path], orig_refs):
        raise ValueError('Power property differs: ' + path)
    compared.append(path)
print(json.dumps({'board_power_properties_equal': len(compared), 'properties': compared}, indent=2))
