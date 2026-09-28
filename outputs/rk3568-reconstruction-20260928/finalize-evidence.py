"""Record final host checks and copy compact evidence out of ignored .deps."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

out = Path(__file__).resolve().parent
repo = out.parents[1]
board = repo/'platforms/rk3568/boards/aiot-3568pq'
dtbuild = repo/'.deps/kernel/aiot-3568pq-firstboot-final-dtb-v2'
config = repo/'.deps/kernel/aiot-3568pq-firstboot-final-config'
dtb = dtbuild/'rk3568-aiot-3568pq-firstboot.dtb'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

commands = []
def run(name, argv, expected=0):
    commands.append({'name': name, 'argv': argv, 'expected_exit': expected})
    result = subprocess.run(argv, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out/(name+'.log')).write_bytes(result.stdout)
    if result.returncode != expected:
        raise RuntimeError(f'{name} exited {result.returncode}; expected {expected}')

run('audit-final', [sys.executable, str(board/'verify-firstboot.py'), str(dtb)])
run('fault-tests-final', [sys.executable, str(board/'test-firstboot-audit.py'), str(dtb), '-v'])
run('config-audit-final', [sys.executable, str(repo/'scripts/prepare-linux-config.py'),
                        '--candidate', str(board/'firstboot-candidate.json'), '--check-config', str(config/'.config')])
before = {p.name: sha(p) for p in dtbuild.iterdir() if p.is_file()}
run('nonempty-output-refused', [sys.executable, str(board/'build-firstboot.py'), '--kernel',
                              str(repo/'third_party/linux-rk3588'), '--dtc',
                              str(repo/'.deps/kernel/aiot-3568pq-final/scripts/dtc/dtc'), '--output', str(dtbuild)], 2)
assert before == {p.name: sha(p) for p in dtbuild.iterdir() if p.is_file()}

objects = ['drivers/mfd/rk808.o', 'drivers/regulator/fan53555.o', 'drivers/regulator/rk808-regulator.o',
           'drivers/soc/rockchip/io-domain.o', 'drivers/mmc/host/sdhci-of-dwcmshc.o',
           'drivers/usb/host/ehci-platform.o', 'drivers/usb/host/ohci-platform.o',
           'drivers/phy/rockchip/phy-rockchip-inno-usb2.o',
           'drivers/soc/rockchip/fiq_debugger/rk_fiq_debugger.o', 'drivers/thermal/rockchip_thermal.o']
object_records = []
for relative in objects:
    path = config/relative
    data = path.read_bytes()
    assert data[:6] == b'\x7fELF\x02\x01' and int.from_bytes(data[18:20], 'little') == 183
    object_records.append({'path': relative, 'sha256': sha(path), 'machine': 'AArch64'})

for name in ['manifest.json', 'audit.json', 'dtc.log', 'baseline-dtc.log', 'commands.json',
             'commands.sh', 'firstboot.compiled.dts', 'rk3568-aiot-3568pq-firstboot.dtb']:
    shutil.copyfile(dtbuild/name, out/name)
shutil.copyfile(config/'kernel-config-manifest.json', out/'kernel-config-manifest.json')
shutil.copyfile(config/'.config', out/'firstboot.config')
(out/'object-manifest.json').write_text(json.dumps(object_records, indent=2)+'\n')
(out/'final-check-commands.json').write_text(json.dumps(commands, indent=2)+'\n')
hash_names = ['rk3568-aiot-3568pq-firstboot.dtb', 'firstboot.compiled.dts', 'firstboot.config',
              'manifest.json', 'audit.json', 'kernel-config-manifest.json', 'power-comparison.json',
              'object-manifest.json']
(out/'SHA256SUMS').write_text(''.join(sha(out/name)+'  '+name+'\n' for name in hash_names))
print(json.dumps({'dtb_audit_checks': json.loads((out/'audit.json').read_text())['checks_passed'],
                  'fault_injection_tests': 8, 'aarch64_driver_objects': len(object_records),
                  'nonempty_output_refused_without_changes': True, 'deployable': False}, indent=2))
