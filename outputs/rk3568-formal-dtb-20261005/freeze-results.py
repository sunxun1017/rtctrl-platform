#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify completed evidence and seal only this task's owned files plus locked inputs."""
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads((HERE / path).read_text())


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    out = HERE / 'sealed-v1'
    require(not out.exists(), 'Fresh seal required')
    emmc = read('build/emmc-v1/manifest.json')
    red = read('build/baseline-red-v1/result.json')
    green = read('build/audit-green-v1/result.json')
    warning = read('build/dtc-warning-audit-v1/result.json')
    match = read('build/linux-match-v1/result.json')
    usb = read('build/usb-closure-v3/result.json')
    source = read('build/usb-source-v1/result.json')
    candidate = HERE / 'build/emmc-v1/audio-emmc-compatible.dtb'
    expected = 'cb3028a4dab33596532557ef59ea8fc99d1517c2474f2816900238ce53cdd279'
    require(candidate.stat().st_size == 163181 and sha(candidate.read_bytes()) == expected, 'Candidate identity')
    require(not red['accepted'] and red['reason'] == 'Deployed U-Boot eMMC compatible is missing', 'True baseline red required')
    require(green['accepted'] and len(green['negative_cases']) == 21 and
            all(case['rejected'] for case in green['negative_cases']), '21 actual rejected DTBs required')
    require(green['candidate_sha256'] == emmc['candidate_sha256'] == match['candidate_sha256'] == usb['candidate_sha256'] == expected,
            'All completed evidence must bind same candidate')
    require(len(emmc['real_libfdt_runs']) == 3 and all(case['sha256'] == expected for case in emmc['real_libfdt_runs']),
            'Real deterministic libfdt evidence required')
    require(warning['decode_diagnostics_same'] and warning['encode_diagnostics_same'] and warning['new_dtc_diagnostics'] == 0,
            'Both DTC paths must introduce no diagnostic')
    require(len(match['receipts']) == 2 and all(case['passed'] == case['total'] == 7 and
            case['compile_exit_code'] == case['run_exit_code'] == 0 for case in match['receipts']), 'Actual Linux matcher result')
    require(usb['original_closed_nodes'] == 42 and usb['candidate_closed_nodes'] == 41 and
            usb['all_graph_references_resolved'], 'Complete described USB closure required')
    require(all(value == 'y' for value in source['required_builtin'].values()), 'Actual builtin config required')
    external = {}
    for report in (emmc, match, source):
        for name, digest in report['inputs_sha256'].items():
            path = ROOT / name
            require(path.is_file() and sha(path.read_bytes()) == digest, 'Input changed: ' + name)
            external[path.relative_to(ROOT).as_posix()] = digest
    lib = ROOT / 'outputs/rk3568-boot-package-20261005/build/libfdt-v2/libfdt-locked.so'
    require(sha(lib.read_bytes()) == emmc['real_libfdt_sha256'], 'Real libfdt changed')
    external[lib.relative_to(ROOT).as_posix()] = sha(lib.read_bytes())
    owned = sorted(path for path in HERE.rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    inventory = {path.relative_to(ROOT).as_posix(): sha(path.read_bytes()) for path in owned}
    out.mkdir()
    for path in owned:
        destination = out / 'snapshot' / path.relative_to(HERE)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        with destination.open('xb') as stream:
            stream.write(data)
        require(sha(destination.read_bytes()) == sha(data), 'Owned evidence copy mismatch')
    report = {
        'status': 'LIMITED_EMMC_COMPATIBLE_OFFLINE_VERIFIED_USB_PLAN_ONLY',
        'candidate_sha256': expected, 'candidate_bytes': 163181,
        'emmc_compatible_only_changed': True, 'real_libfdt_builds': 3,
        'dtc_runs': 4, 'dtc_decode_and_encode_new_diagnostics': 0,
        'negative_dtbs_rejected': 21, 'linux_matcher_host': '7/7', 'linux_matcher_asan_ubsan': '7/7',
        'usb_closed_nodes_original': 42, 'usb_closed_nodes_candidate': 41,
        'usb_status_and_supply_modifications': False,
        'early_dm_tested': False, 'emmc_probe_io_tested': False, 'usb_recovery_tested': False,
        'formal_boot_package_generated': False, 'image_built': False, 'formal_flash_ready': False,
        'board_operated': False, 'wsl_tun_network_changed': False,
        'owned_files': len(inventory), 'files_sha256': inventory, 'inputs_sha256': external,
        'snapshot_is_exact': True,
    }
    with (out / 'manifest.json').open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('status', 'owned_files', 'candidate_sha256')}))


if __name__ == '__main__':
    main()
