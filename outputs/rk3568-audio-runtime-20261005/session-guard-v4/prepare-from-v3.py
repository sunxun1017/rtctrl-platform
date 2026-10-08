#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create v4 without changing any frozen prior version."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = HERE.parent / 'session-guard-v3'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = {}
    for version in ['v1', 'v2', 'v3']:
        directory = HERE.parent / ('session-guard-' + version)
        listing = directory / 'SHA256SUMS'
        count = 0
        for row in listing.read_text().splitlines():
            expected, name = row.split('  ', 1)
            path = directory / name
            if not path.is_file() or path.is_symlink() or sha(path) != expected:
                raise ValueError('Prior frozen mismatch: ' + str(path))
            count += 1
        baseline[version] = {'SHA256SUMS_sha256': sha(listing), 'verified_files': count}
    red = json.loads((HERE / 'clock-stage-red-v3/result.json').read_text())
    if not red['expected_red'] or len(red['targets']) != 3 or any(
            not item['expected_red_reproduced'] or item['cases'] != 2 or item['exit']
            for item in red['targets']):
        raise ValueError('Actual production clock stage red must exist first')
    copied = {}
    for name in ['audio-session-guard.c', 'guard-parser.h', 'model-driver.c',
                 'test-models.py', 'build-freeze.py', 'README.md', 'PLAN.md',
                 'canonical-device-model.c', 'test-canonical-device.py']:
        target = HERE / name
        if target.exists():
            raise ValueError('New output already exists: ' + name)
        target.write_bytes((PRIOR / name).read_bytes())
        copied[name] = sha(target)
    raw = ROOT / 'outputs/rk3568-pid1-20261005/private/audio-clock-parents-20261006-v1.raw.txt'
    parents = {
        'clk_i2s1_8ch_tx_src': 'gpll',
        'clk_i2s1_8ch_tx_frac': 'clk_i2s1_8ch_tx_src',
        'clk_i2s1_8ch_tx': 'clk_i2s1_8ch_tx_frac',
        'mclk_i2s1_8ch_tx': 'clk_i2s1_8ch_tx',
        'i2s1_mclkout_tx': 'mclk_i2s1_8ch_tx',
        'i2s1_mclkout': 'i2s1_mclkout_tx',
    }
    lines = raw.read_text().splitlines()
    for clock, parent in parents.items():
        if lines.count('CLOCK_PARENT ' + clock + '=' + parent) != 1:
            raise ValueError('Need exact fresh TX cached parent evidence')
    evidence = {
        'root_reported_board_observation': True, 'subagent_board_access': False,
        'raw_path': raw.relative_to(ROOT).as_posix(), 'raw_sha256': sha(raw),
        'codec_source_sha256': '72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64',
        'provider_source_sha256': '563ffe996cfee4103d018b46393a09298fd181291ce512da078bb68ec96869e1',
        'ccf_source_sha256': 'c1b5d1d3bb98bc37a45ed1259acaf805fab2d9ed60a75d31b49e5f4b3a258117',
        'codec_clock_provider': 'cru', 'codec_clock_id': 419,
        'codec_component_probe_holds_one_reference_until_component_remove': True,
        'codec_clock_counts_are_total_ccf_counts_not_per_consumer': True,
        'fixed_tx_cached_parents': parents,
        'shared_gpll_reference_count_constrained': False,
        'inactive_rx_ioe_parent_constrained': False,
        'stages': {'bound': 'TX six enable/prepare=1 protect=0; HCLK=1; other nine=0',
                   'card-unbound': 'TX six=0; HCLK=1; other nine=0',
                   'cpu-unbound': 'All sixteen=0'},
        'gate_does_not_prove_per_consumer_clock_ownership': True,
        'classification_depends_on_exact_codec_source_module_dt_and_single_thread_native_domain': True,
    }
    (HERE / 'clock-profile-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    (HERE / 'prior-frozen-baseline.json').write_text(json.dumps({
        'board_tested': False, 'prior_versions': baseline, 'copied_files': copied,
        'clock_stage_red_result_sha256': sha(HERE / 'clock-stage-red-v3/result.json')
    }, indent=2) + '\n')
    print(json.dumps({'prior_versions_verified': baseline, 'copied': len(copied),
                      'clock_profile_evidence_sha256': sha(HERE / 'clock-profile-evidence.json')}))


if __name__ == '__main__':
    main()
