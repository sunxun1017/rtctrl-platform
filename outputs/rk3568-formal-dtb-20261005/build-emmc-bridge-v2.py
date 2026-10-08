#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Append only the deployed eMMC fallback using locked real libfdt and DTC."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / 'outputs/rk3568-boot-package-20261005'
BASE = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb'
ORIGINAL = PACKAGE / 'build/roundtrip-v1/rsce/arch/arm64/boot/dts/rockchip/rk3568_smdt_3568a_v20.dtb'
EMMC = '/sdhci@fe310000'
OLD = b'rockchip,rk3568-dwcmshc\0rockchip,dwcmshc-sdhci\0'
NEW = OLD + b'snps,dwcmshc-sdhci\0'
DTC = ROOT / '.deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc'
DTC_SHA = '3be6ad1bcef2e36b35624e9f2cd6c13957949e08818868ad04ad070b4fd9e896'
LOCKS = {
    PACKAGE / 'dt-semantics-v2.py': 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56',
    PACKAGE / 'libfdt-v2.py': '9fdba61ae8d7d004ac7f24b7f116f6a314032c01624357f01619f609a5b8a954',
    BASE: '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f',
    ORIGINAL: '83aa4a285dbc8bff3ae3a72a14e371faa54e7598808c4c6ace2834aeb9c9f956',
    DTC: DTC_SHA,
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), PACKAGE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_dtc(argv, stem):
    result = subprocess.run([str(DTC), *argv], capture_output=True, timeout=30)
    stem.with_suffix('.stdout').write_bytes(result.stdout)
    stem.with_suffix('.stderr').write_bytes(result.stderr)
    require(result.returncode == 0, 'DTC rejected ' + str(stem))
    return {'argv': [str(DTC), *argv], 'exit_code': result.returncode,
            'stdout_sha256': sha(result.stdout), 'stderr_sha256': sha(result.stderr),
            'warning_bytes': len(result.stderr)}, result.stdout, result.stderr


def build(out):
    require(out == out.resolve() and out.is_relative_to(HERE / 'build'), 'Own fresh ordinary output required')
    for path, expected in LOCKS.items():
        require(sha(path.read_bytes()) == expected, 'Locked input changed: ' + str(path.relative_to(ROOT)))
    semantic = load('dt-semantics-v2.py')
    bridge = load('libfdt-v2.py')
    baseline, original = BASE.read_bytes(), ORIGINAL.read_bytes()
    before = semantic.parse(baseline)
    require(bytes.fromhex(before['properties'][EMMC + ':compatible']) == OLD, 'Unexpected baseline compatible')
    require(bytes.fromhex(semantic.parse(original)['properties'][EMMC + ':compatible']) ==
            b'rockchip,dwcmshc-sdhci\0snps,dwcmshc-sdhci\0', 'Original fallback identity differs')
    real = bridge.RealLibFdt()
    out.mkdir(parents=True, exist_ok=False)
    dtc_dir = out / 'dtc'
    dtc_dir.mkdir()
    (out / 'audio-baseline.dtb').write_bytes(baseline)
    repeats = []
    for number in range(1, 4):
        opened = real.opened(baseline)
        real.set_property(opened, EMMC, 'compatible', NEW)
        candidate = real.packed(opened)
        after = semantic.parse(candidate)
        require(semantic.diff(before, after) == {EMMC + ':compatible': {'before': OLD.hex(), 'after': NEW.hex()}},
                'Unexpected complete semantic change')
        require(semantic.phandles(before) == semantic.phandles(after), 'Phandle changed')
        repeats.append({'number': number, 'bytes': len(candidate), 'sha256': sha(candidate)})
    require(len({case['sha256'] for case in repeats}) == 1, 'Real libfdt build is not deterministic')
    final = out / 'audio-emmc-compatible.dtb'
    final.write_bytes(candidate)
    dtc_results = []
    warnings = []
    for name, path in (('baseline', out / 'audio-baseline.dtb'), ('candidate', final)):
        result, dts, warning = run_dtc(['-I', 'dtb', '-O', 'dts', str(path)], dtc_dir / (name + '-decode'))
        (dtc_dir / (name + '.dts')).write_bytes(dts)
        result['stage'] = name + '-decode'
        dtc_results.append(result)
        warnings.append(warning.replace(str(path).encode(), b'<input>'))
        result, rebuilt, _ = run_dtc(['-I', 'dts', '-O', 'dtb', str(dtc_dir / (name + '.dts'))],
                                     dtc_dir / (name + '-encode'))
        result['stage'] = name + '-encode'
        dtc_results.append(result)
        (dtc_dir / (name + '-roundtrip.dtb')).write_bytes(rebuilt)
        require(semantic.parse(rebuilt) == semantic.parse(path.read_bytes()), 'DTC roundtrip full semantics changed')
    require(warnings[0] == warnings[1], 'Candidate introduces DTC warning changes')
    inputs = [*LOCKS, PACKAGE / 'FORMAL-EARLY-REVIEW.md',
              ROOT / 'third_party/linux-rk3588/drivers/mmc/host/sdhci-of-dwcmshc.c',
              ROOT / '.deps/kernel/aiot-3568pq-audio-v1/.config', Path(__file__)]
    manifest = {
        'status': 'LIMITED_EMMC_COMPATIBLE_OFFLINE_ONLY',
        'baseline_sha256': sha(baseline), 'candidate_sha256': sha(candidate),
        'baseline_bytes': len(baseline), 'candidate_bytes': len(candidate),
        'allowed_diff': {EMMC + ':compatible': {'before': OLD.hex(), 'after': NEW.hex()}},
        'compatible': NEW[:-1].decode('ascii').split('\0'),
        'all_other_properties_nodes_metadata_unchanged': True,
        'phandles_unchanged': True, 'reservations_unchanged': True,
        'usb_status_and_supplies_unchanged': True, 'real_libfdt_sha256': bridge.LIB_SHA,
        'real_libfdt_runs': repeats, 'dtc_sha256': DTC_SHA, 'dtc_runs': dtc_results,
        'dtc_baseline_warning_bytes': len(warnings[0]), 'dtc_added_warnings': 0,
        'board_tested': False, 'early_dm_tested': False, 'emmc_io_tested': False,
        'usb_recovery_tested': False, 'formal_flash_ready': False,
        'chosen_overlay_prerequisites_added': False,
        'inputs_sha256': {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in inputs},
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({key: manifest[key] for key in ('candidate_bytes', 'candidate_sha256', 'dtc_added_warnings')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    build(Path(args.out).absolute())


if __name__ == '__main__':
    main()
