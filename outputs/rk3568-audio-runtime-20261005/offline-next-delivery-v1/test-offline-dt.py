#!/usr/bin/env python3
"""Finite DT contract checks; the unmodified prior shim is the actual red input."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CPU = '/i2s@fe410000'
CODEC = '/i2c@fdd40000/pmic@20/codec'
FLAG = 'rockchip,checked-shared-params-48k'


def load(path):
    spec = importlib.util.spec_from_file_location('dt_contract_semantics', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    semantic = load(ROOT / 'outputs/rk3568-boot-package-20261005/dt-semantics-v2.py')
    prior = semantic.parse((HERE.parent / 'build/audio-ram-shim-v1/audio-ram-shim.dtb').read_bytes())
    candidate = semantic.parse((ROOT / args.candidate).read_bytes())
    expected = {path + ':' + FLAG: {'before': None, 'after': ''} for path in (CPU, CODEC)}
    difference = semantic.diff(prior, candidate)
    passed = difference == expected and semantic.phandles(prior) == semantic.phandles(candidate)
    print(json.dumps({'paired_empty_flags_only': passed, 'actual_complete_difference': difference,
                      'expected_complete_difference': expected, 'board_tested': False}, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
