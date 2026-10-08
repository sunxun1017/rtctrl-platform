#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Audit one allowed compatible change against the exact tested audio tree."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / 'outputs/rk3568-boot-package-20261005'
BASE = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb'
BASE_SHA = '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'
EMMC = '/sdhci@fe310000'
WANT = b'rockchip,rk3568-dwcmshc\0rockchip,dwcmshc-sdhci\0snps,dwcmshc-sdhci\0'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), PACKAGE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(candidate):
    semantic = load('dt-semantics-v2.py')
    baseline = BASE.read_bytes()
    require(len(baseline) == 163285 and hashlib.sha256(baseline).hexdigest() == BASE_SHA,
            'Exact tested audio baseline required')
    before, after = semantic.parse(baseline), semantic.parse(candidate)
    compatible = bytes.fromhex(after['properties'][EMMC + ':compatible'])
    require(compatible.endswith(b'\0') and b'snps,dwcmshc-sdhci\0' in compatible,
            'Deployed U-Boot eMMC compatible is missing')
    require(compatible == WANT, 'Linux RK3568 first match/order must be preserved')
    allowed = {EMMC + ':compatible': {
        'before': b'rockchip,rk3568-dwcmshc\0rockchip,dwcmshc-sdhci\0'.hex(),
        'after': WANT.hex()}}
    require(semantic.diff(before, after) == allowed, 'Only one compatible property may change')
    require(semantic.phandles(before) == semantic.phandles(after), 'All phandles must remain identical')
    return {'node_count': len(after['nodes']), 'property_count': len(after['properties']),
            'phandle_count': len(semantic.phandles(after)), 'full_diff': allowed,
            'existing_linux_variant_preserved': True, 'deployed_uboot_string_matches': True}


def mutate(data, path, name, value):
    real = load('libfdt-v2.py').RealLibFdt()
    base = real.opened(data)
    real.set_property(base, path, name, value)
    return real.packed(base)


def boundaries(candidate, out):
    cases = [
        ('old_baseline_lacks_deployed_match', BASE.read_bytes()),
        ('generic_fallback_first', mutate(candidate, EMMC, 'compatible',
             b'snps,dwcmshc-sdhci\0rockchip,rk3568-dwcmshc\0rockchip,dwcmshc-sdhci\0')),
        ('rk3568_variant_removed', mutate(candidate, EMMC, 'compatible', b'snps,dwcmshc-sdhci\0')),
        ('unterminated_compatible', mutate(candidate, EMMC, 'compatible', WANT[:-1])),
        ('duplicate_fallback', mutate(candidate, EMMC, 'compatible', WANT + b'snps,dwcmshc-sdhci\0')),
        ('unrelated_compatible', mutate(candidate, EMMC, 'compatible', WANT + b'other,driver\0')),
        ('emmc_disabled', mutate(candidate, EMMC, 'status', b'disabled\0')),
        ('clock_reference_changed', mutate(candidate, EMMC, 'clocks', bytes.fromhex('000000230000007d'))),
        ('reset_reference_changed', mutate(candidate, EMMC, 'resets', bytes.fromhex('0000002300000079'))),
        ('emmc_phandle_changed', mutate(candidate, EMMC, 'phandle', struct.pack('>I', 0x2fa))),
        ('emmc_duplicate_phandle', mutate(candidate, EMMC, 'phandle', struct.pack('>I', 0x2f9))),
        ('usb_parent_enabled', mutate(candidate, '/usbdrd', 'status', b'okay\0')),
        ('usb_child_enabled', mutate(candidate, '/usbdrd/dwc3@fcc00000', 'status', b'okay\0')),
        ('otg_phy_enabled', mutate(candidate, '/usb2-phy@fe8a0000/otg-port', 'status', b'okay\0')),
        ('new_vbus_supply', mutate(candidate, '/usb2-phy@fe8a0000/otg-port', 'vbus-supply', struct.pack('>I', 0x2fa))),
        ('chosen_bootargs_changed', mutate(candidate, '/chosen', 'bootargs', b'console=other\0')),
        ('new_chosen_property', mutate(candidate, '/chosen', 'formal-test-only', b'')),
        ('truncated_fdt', candidate[:-1]),
        ('wrong_magic', b'BAD!' + candidate[4:]),
        ('extra_tail', candidate + b'\0'),
    ]
    reserved = bytearray(candidate)
    reserve_offset = struct.unpack_from('>I', reserved, 16)[0]
    struct.pack_into('>Q', reserved, reserve_offset, 0xa100008)
    cases.append(('reservation_changed', bytes(reserved)))
    results = []
    for name, blob in cases:
        (out / (name + '.dtb')).write_bytes(blob)
        try:
            audit(blob)
        except (ValueError, KeyError, UnicodeError, struct.error) as error:
            results.append({'name': name, 'rejected': True, 'reason': str(error),
                            'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()})
        else:
            results.append({'name': name, 'rejected': False})
    require(all(case['rejected'] for case in results), 'Bad candidate unexpectedly passed')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--boundaries', action='store_true')
    args = parser.parse_args()
    out = Path(args.out).absolute()
    require(out == out.resolve() and out.is_relative_to(HERE / 'build'), 'Own fresh ordinary output required')
    out.mkdir(parents=True, exist_ok=False)
    blob = Path(args.candidate).read_bytes()
    report = {'candidate': args.candidate, 'candidate_sha256': hashlib.sha256(blob).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'board_tested': False, 'early_dm_tested': False, 'usb_recovery_tested': False}
    try:
        report['audit'] = audit(blob)
        report['accepted'] = True
        if args.boundaries:
            bad = out / 'rejected-dtbs'
            bad.mkdir()
            report['negative_cases'] = boundaries(blob, bad)
    except (ValueError, KeyError, UnicodeError, struct.error) as error:
        report['accepted'] = False
        report['reason'] = str(error)
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('accepted', 'candidate_sha256')}))
    if not report['accepted']:
        print(report['reason'], file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
