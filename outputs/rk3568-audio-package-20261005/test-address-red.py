#!/usr/bin/env python3
"""Save the missing dynamic Image/gd FDT policy before the new implementation."""
import argparse
import importlib.util
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    output = Path(args.out).absolute()
    assert output == output.resolve() and output.is_relative_to(HERE / 'build')
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'outputs/rk3568-boot-package-20261005/build-ram-candidate-v2.py'
    spec = importlib.util.spec_from_file_location('old_fixed_policy', source)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    image = bytearray((ROOT / 'outputs/rk3568-rcu-reset-20261004/Image').read_bytes())
    header = {'kernel_addr': 0x280000, 'ramdisk_addr': 0xa200000,
              'second_addr': 0xa100000, 'dtb_addr': 0xa100000}
    sizes = {'kernel': len(image), 'ramdisk': 972203, 'second': 4591616, 'dtb': 163204}
    cases = []
    try:
        struct.pack_into('<Q', image, 16, 35389440 + 2 * 1024 * 1024)
        result = legacy.address_analysis(image, header, sizes)
        assert result['image_header']['image_size'] == 35389440 + 2 * 1024 * 1024
        cases.append({'name': 'accept-dynamic-valid-image-size', 'passed': True})
    except Exception as error:
        cases.append({'name': 'accept-dynamic-valid-image-size', 'passed': False,
                      'error': type(error).__name__ + ': ' + str(error)})
    struct.pack_into('<Q', image, 16, 35389440)
    try:
        result = legacy.address_analysis(image, header, sizes)
        assert result.get('actual_plan', {}).get('fdt_workspace') == [0xa100000, 0xa140000]
        cases.append({'name': 'plan-fdt-at-gd-workspace', 'passed': True})
    except Exception as error:
        cases.append({'name': 'plan-fdt-at-gd-workspace', 'passed': False,
                      'error': type(error).__name__ + ': ' + str(error)})
    (output / 'result.json').write_text(json.dumps({'red_expected': True, 'cases': cases}, indent=2) + '\n')
    print(json.dumps(cases))
    raise SystemExit(0 if all(item['passed'] for item in cases) else 1)


if __name__ == '__main__':
    main()
