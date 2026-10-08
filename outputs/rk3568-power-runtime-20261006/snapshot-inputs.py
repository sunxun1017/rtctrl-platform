#!/usr/bin/env python3
"""Preserve exact owned-kernel inputs before an offline battery candidate."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v1'

def main():
    output = HERE / 'original-v1'
    output.mkdir(exist_ok=False)
    names = [
        'drivers/power/supply/rk817_battery.c',
        'drivers/power/supply/Kconfig', 'drivers/power/supply/Makefile',
        'drivers/mfd/rk808.c', 'include/linux/mfd/rk808.h',
        'include/linux/wakelock.h', 'include/linux/workqueue.h',
        'kernel/workqueue.c', 'lib/devres.c', 'drivers/base/devres.c',
        'kernel/irq/devres.c', 'drivers/power/supply/power_supply_core.c',
        'Documentation/devicetree/bindings/power_supply/rk817-battery.txt',
    ]
    inventory = {}
    for name in names:
        source = SOURCE / name
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        inventory[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    extras = {
        'audio.config': ROOT / '.deps/kernel/aiot-3568pq-audio-v1/.config',
        'android-original.dtb': ROOT / 'outputs/android-board-20260928/fdt.dtb',
    }
    for name, source in extras.items():
        shutil.copyfile(source, output / name)
        inventory[name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps({
        'files_sha256': inventory, 'hardware_access': False,
        'source': SOURCE.relative_to(ROOT).as_posix(),
    }, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'files': len(inventory), 'driver': inventory[names[0]]}))

if __name__ == '__main__':
    main()
