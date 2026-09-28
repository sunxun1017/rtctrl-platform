#!/usr/bin/env python3
"""Audit the compiled firstboot DTB; no hardware operations."""
import argparse
import json
from pathlib import Path
import struct


def read_dtb(path):
    blob = path.read_bytes()
    magic, size, structure, strings, reserve, version, _, _, strsize, stsize = struct.unpack_from('>10I', blob)
    if magic != 0xd00dfeed or size != len(blob) or version < 17:
        raise ValueError('Invalid DTB header')
    if strings + strsize > size or structure + stsize > size:
        raise ValueError('Invalid DTB block bounds')
    props, stack, reservations = {}, [], []
    while True:
        address, length = struct.unpack_from('>QQ', blob, reserve)
        reserve += 16
        if not address and not length:
            break
        reservations.append([address, length])
    pos = structure
    while pos < structure + stsize:
        token = struct.unpack_from('>I', blob, pos)[0]
        pos += 4
        if token == 1:
            end = blob.index(b'\0', pos)
            stack.append(blob[pos:end].decode())
            pos = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, offset = struct.unpack_from('>II', blob, pos)
            pos += 8
            end = blob.index(b'\0', strings + offset, strings + strsize)
            name = blob[strings + offset:end].decode()
            props['/'.join(stack) + '/' + name] = blob[pos:pos + length]
            pos = (pos + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack:
                raise ValueError('Unclosed DTB node')
            return props, reservations
        else:
            raise ValueError('Unexpected DTB token')
    raise ValueError('Missing DTB end token')


def audit(tree, reservations):
    checks = []

    def data(path):
        return tree[path]

    def cells(path):
        value = data(path)
        return list(struct.unpack('>' + 'I' * (len(value) // 4), value))

    def text(path):
        return data(path).rstrip(b'\0').decode()

    def check(name, condition):
        if not condition:
            raise ValueError(name)
        checks.append(name)

    handles = {cells(p)[0]: p.rsplit('/', 1)[0] for p in tree if p.endswith('/phandle')}

    def target(path):
        return handles[cells(path)[0]]

    pmic = '/i2c@fdd40000/pmic@20'
    regs = pmic + '/regulators'
    io = '/syscon@fdc20000/io-domains'
    for domain, regulator in {'pmuio2': 'LDO_REG6', 'vccio1': 'LDO_REG4',
                              'vccio3': 'LDO_REG5', 'vccio4': 'DCDC_REG5',
                              'vccio5': 'SWITCH_REG1', 'vccio6': 'DCDC_REG5',
                              'vccio7': 'SWITCH_REG1'}.items():
        check(domain + ' supply mapping', target(io + '/' + domain + '-supply') == regs + '/' + regulator)
    check('1.8V IO supply', cells(regs + '/DCDC_REG5/regulator-min-microvolt') == [1800000])
    check('3.1V codec IO supply', cells(regs + '/LDO_REG4/regulator-min-microvolt') == [3100000])
    for regulator in ['DCDC_REG1', 'DCDC_REG2', 'DCDC_REG4']:
        check(regulator + ' lower bound', cells(regs + '/' + regulator + '/regulator-min-microvolt') == [825000])
    check('DDR voltage not guessed', regs + '/DCDC_REG3/regulator-min-microvolt' not in tree)
    check('DDR supply remains on', regs + '/DCDC_REG3/regulator-always-on' in tree)
    check('CPU regulator mapping', target('/cpus/cpu@0/cpu-supply') == '/i2c@fdd40000/tcs4525@1c')
    check('TCS actual compatible', text('/i2c@fdd40000/tcs4525@1c/compatible') == 'tcs,tcs452x')
    check('TCS initial mode', cells('/i2c@fdd40000/tcs4525@1c/regulator-initial-mode') == [1])
    for name, mux, config in [('pmic_int', 0, '/pinctrl/pcfg-pull-up'),
                              ('soc_slppin_slp', 1, '/pinctrl/pcfg-pull-up'),
                              ('soc_slppin_gpio', 0, '/pinctrl/pcfg-output-low-pull-down')]:
        pins = cells('/pinctrl/pmic/' + name + '/rockchip,pins')
        check(name + ' wiring', pins[:3] == [0, 3 if name == 'pmic_int' else 2, mux])
        check(name + ' pull/level', handles[pins[3]] == config)
    check('52MHz eMMC', cells('/sdhci@fe310000/max-frequency') == [52000000])
    check('5.10 eMMC binding', data('/sdhci@fe310000/compatible').split(b'\0')[0] == b'rockchip,rk3568-dwcmshc')
    check('eMMC controller resets retained', len(cells('/sdhci@fe310000/resets')) == 10)
    check('eMMC 8bit', cells('/sdhci@fe310000/bus-width') == [8])
    check('no inferred USB power GPIO', '/vcc5v0-host-regulator/gpio' not in tree)
    for phy in ['usb2-phy@fe8a0000', 'usb2-phy@fe8b0000']:
        check(phy + ' host supply', target('/' + phy + '/host-port/phy-supply') == '/vcc5v0-host-regulator')
    for address in ['fd800000', 'fd840000', 'fd880000', 'fd8c0000']:
        check('USB host ' + address, text('/usb@' + address + '/status') == 'okay')
    check('FIQ baud', cells('/fiq-debugger/rockchip,baudrate') == [1500000])
    for node in ['/serial@fdd50000', '/serial@fe660000', '/dmc', '/rockchip-suspend',
                 '/gpu@fde60000', '/npu@fde40000', '/dsi@fe060000', '/dwmmc@fe2c0000',
                 '/mipi-csi2-hw@fdfb0000', '/display-subsystem']:
        check(node + ' disabled', text(node + '/status') == 'disabled')
    check('no serial identifier', '/serial-number' not in tree)
    args = text('/chosen/bootargs')
    check('initramfs only bootargs', 'rdinit=/init' in args and 'androidboot' not in args and 'root=' not in args)
    check('captured RAM holes retained', cells('/memory@200000/reg') == [0, 0x200000, 0, 0x8200000, 0, 0x9400000, 0, 0xe6c00000, 1, 0xf0000000, 0, 0x10000000])
    check('captured FDT reservations retained', reservations == [[0xa100000, 0x25000], [0xa200000, 0xc8c20]])
    return {'checks_passed': len(checks), 'checks': checks, 'board_boot_tested': False, 'deployable': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtb', type=Path)
    options = parser.parse_args()
    print(json.dumps(audit(*read_dtb(options.dtb)), indent=2))
