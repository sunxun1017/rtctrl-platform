#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy current readonly source/config inputs and preserve the relevant excerpts."""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / 'third_party/linux-rk3588'
RANGES = {
    'drivers/usb/dwc3/dwc3-of-simple.c': [(34, 96), (173, 195)],
    'drivers/usb/dwc3/dwc3-rockchip-inno.c': [(261, 276)],
    'drivers/usb/dwc3/core.c': [(997, 1017), (1208, 1239), (2070, 2081)],
    'drivers/usb/host/xhci-plat.c': [(353, 367)],
    'drivers/phy/rockchip/phy-rockchip-inno-usb2.c': [(2110, 2180), (2310, 2460), (4110, 4123)],
    'drivers/phy/rockchip/phy-rockchip-naneng-combphy.c': [(294, 380), (1283, 1300)],
    'drivers/phy/phy-core.c': [(900, 920)],
    'drivers/soc/rockchip/pm_domains.c': [(990, 1007), (1050, 1065), (1098, 1114)],
    'drivers/mmc/host/sdhci-of-dwcmshc.c': [(536, 559)],
    'drivers/of/base.c': [(484, 519), (1081, 1101)],
}
REQUIRED = ('USB_DWC3', 'USB_DWC3_DUAL_ROLE', 'USB_DWC3_OF_SIMPLE', 'USB_XHCI_PLATFORM',
            'USB_EHCI_HCD_PLATFORM', 'USB_OHCI_HCD_PLATFORM', 'PHY_ROCKCHIP_INNO_USB2',
            'PHY_ROCKCHIP_NANENG_COMBO_PHY', 'CPU_RK3568', 'REGULATOR_FIXED_VOLTAGE')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out).absolute()
    if out != out.resolve() or not out.is_relative_to(HERE / 'build'):
        raise ValueError('Own fresh ordinary output required')
    config = ROOT / '.deps/kernel/aiot-3568pq-audio-v1/.config'
    values = dict(line.split('=', 1) for line in config.read_text().splitlines() if line.startswith('CONFIG_') and '=' in line)
    if any(values.get('CONFIG_' + name) != 'y' for name in REQUIRED):
        raise ValueError('Current expected built-in config changed')
    out.mkdir(parents=True, exist_ok=False)
    source_dir = out / 'source-snapshot'
    source_dir.mkdir()
    inventory, excerpts = {}, {}
    for name, ranges in RANGES.items():
        data = (KERNEL / name).read_bytes()
        destination = source_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        if sha(destination.read_bytes()) != sha(data):
            raise ValueError('Source copy mismatch')
        inventory[str((KERNEL / name).relative_to(ROOT))] = sha(data)
        lines = data.decode().splitlines()
        excerpts[name] = [{'first_line': begin, 'last_line': end,
                           'source': '\n'.join(lines[begin - 1:end])} for begin, end in ranges]
    (source_dir / 'kernel.config').write_bytes(config.read_bytes())
    inventory[str(config.relative_to(ROOT))] = sha(config.read_bytes())
    inventory[str(Path(__file__).relative_to(ROOT))] = sha(Path(__file__).read_bytes())
    report = {'actual_source_config_snapshotted': True,
              'required_builtin': {name: values['CONFIG_' + name] for name in REQUIRED},
              'source_excerpts': excerpts, 'inputs_sha256': inventory,
              'board_tested': False, 'usb_probe_or_electrical_tested': False}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'sources': len(RANGES), 'builtins': len(REQUIRED), 'board_tested': False}))


if __name__ == '__main__':
    main()
