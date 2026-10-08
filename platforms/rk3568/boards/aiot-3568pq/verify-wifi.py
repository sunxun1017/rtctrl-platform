#!/usr/bin/env python3
"""Audit original SDIO wiring plus every existing firstboot baseline check."""
import argparse
import importlib.util
import json
from pathlib import Path
import struct

spec = importlib.util.spec_from_file_location('firstboot', Path(__file__).with_name('verify-firstboot.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def audit(tree, reservations):
    checks = []

    def check(name, condition):
        if not condition:
            raise ValueError(name)
        checks.append(name)

    def cells(path):
        value = tree[path]
        return list(struct.unpack('>' + 'I' * (len(value) // 4), value))

    def text(path):
        return tree[path].rstrip(b'\0').decode()

    handles = {cells(p)[0]: p.rsplit('/', 1)[0] for p in tree if p.endswith('/phandle')}

    def refs(path):
        return [handles[x] for x in cells(path)]

    sdio = '/dwmmc@fe2c0000'
    pwr = '/sdio-pwrseq'
    wlan = '/wireless-wlan'
    check('original Wi-Fi controller enabled', text(sdio + '/status') == 'okay')
    check('SDIO4 bus', cells(sdio + '/bus-width') == [4])
    check('original 150MHz upper limit', cells(sdio + '/max-frequency') == [150000000])
    for prop in ['supports-sdio', 'cap-sd-highspeed', 'cap-sdio-irq', 'non-removable',
                 'keep-power-in-suspend', 'sd-uhs-sdr104']:
        check(prop, tree.get(sdio + '/' + prop) == b'')
    check('no inferred SDIO rails', all(sdio + '/' + x not in tree for x in ['vmmc-supply', 'vqmmc-supply']))
    check('controller uses dedicated pwrseq', refs(sdio + '/mmc-pwrseq') == [pwr])
    check('simple pwrseq', text(pwr + '/compatible') == 'mmc-pwrseq-simple')
    clock = cells(pwr + '/clocks')
    check('PMIC clkout2', handles[clock[0]] == '/i2c@fdd40000/pmic@20' and clock[1:] == [1])
    check('external clock name', text(pwr + '/clock-names') == 'ext_clock')
    check('400ms post-on', cells(pwr + '/post-power-on-delay-ms') == [400])
    check('500ms off', cells(pwr + '/power-off-delay-us') == [500000])
    reset = cells(pwr + '/reset-gpios')
    check('GPIO2_B1 reset active-low', handles[reset[0]] == '/pinctrl/gpio2@fe750000' and reset[1:] == [9, 1])
    wake = cells(wlan + '/WIFI,host_wake_irq')
    check('GPIO2_B2 wake active-high', handles[wake[0]] == '/pinctrl/gpio2@fe750000' and wake[1:] == [10, 0])
    check('Rockchip wlan platform', text(wlan + '/compatible') == 'wlan-platdata')
    check('platform enabled', text(wlan + '/status') == 'okay')
    check('captured chip string', text(wlan + '/wifi_chip_type') == 'ap6398s')
    check('no competing power/reset GPIO', all(wlan + '/' + x not in tree for x in ['WIFI,poweren_gpio', 'WIFI,reset_gpio']))
    check('pwrseq GPIO pinctrl', refs(pwr + '/pinctrl-0') == ['/pinctrl/wifi/wifi-enable'])
    check('wake pinctrl', refs(wlan + '/pinctrl-0') == ['/pinctrl/wifi/wifi-host-wake-irq'])
    pins = refs(sdio + '/pinctrl-0')
    check('SDIO data/CMD/CLK pinctrl', pins == ['/pinctrl/sdmmc1/sdmmc1-bus4',
                                              '/pinctrl/sdmmc1/sdmmc1-cmd', '/pinctrl/sdmmc1/sdmmc1-clk'])
    for path, expected_pins in zip(pins, [[3, 4, 5, 6], [7], [8]]):
        config = cells(path + '/rockchip,pins')
        expected = []
        for pin in expected_pins:
            expected.extend([2, pin, 1])
        check(path + ' wiring', [x for i, x in enumerate(config) if i % 4 != 3] == expected)
        check(path + ' pull-up/drive', all(handles[config[i]] == '/pinctrl/pcfg-pull-up-drv-level-2'
                                         for i in range(3, len(config), 4)))
    for node, pin, config in [('wifi-enable', 9, '/pinctrl/pcfg-pull-none'),
                              ('wifi-host-wake-irq', 10, '/pinctrl/pcfg-pull-up')]:
        value = cells('/pinctrl/wifi/' + node + '/rockchip,pins')
        check(node + ' GPIO wiring', value[:3] == [2, pin, 0] and len(value) == 4)
        check(node + ' bias', handles[value[3]] == config)
    for addr in ['fe2b0000', 'fe000000']:
        check('unused MMC ' + addr + ' disabled', text('/dwmmc@' + addr + '/status') == 'disabled')

    # This one intentional extension is checked above, then normalized only
    # for the unmodified baseline audit. All its other checks still run.
    baseline_tree = dict(tree)
    baseline_tree[sdio + '/status'] = b'disabled\0'
    result = base.audit(baseline_tree, reservations)
    result['checks'] += checks
    result['checks_passed'] = len(result['checks'])
    result['variant'] = 'wifi'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtb', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(*base.read_dtb(args.dtb)), indent=2))
