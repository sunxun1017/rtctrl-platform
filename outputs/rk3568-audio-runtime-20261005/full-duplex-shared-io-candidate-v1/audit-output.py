#!/usr/bin/env python3
"""Final finite audit; no recursive SDK inventory and no kernel build."""
import difflib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARAMS = HERE.parent / 'full-duplex-params-candidate-v1'
spec = importlib.util.spec_from_file_location('source_utils', PARAMS / 'model-v4/source_utils.py')
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)
function, sha = utils.function, utils.sha


def main():
    output = HERE / 'final-audit-v1.json'
    if output.exists():
        raise ValueError('Fresh output required')
    old = json.loads((HERE / 'inputs-v1/manifest.json').read_text())
    candidate = json.loads((HERE / 'source-manifest-v3.json').read_text())
    checks = {}
    for rel, record in old['files'].items():
        before = (HERE / 'inputs-v1' / rel).read_bytes()
        original = (ROOT / record['source']).read_bytes()
        after = (HERE / 'source-v3' / rel).read_bytes()
        checks['original_preserved:' + rel] = sha(before) == sha(original) == record['sha256']
        expected = candidate['files'].get(rel, {}).get('candidate_sha256', record['sha256'])
        checks['private_identity:' + rel] = sha(after) == expected
    rel = 'sound/soc/codecs/rk817_codec.c'
    before = (HERE / 'inputs-v1' / rel).read_text()
    after = (HERE / 'source-v3' / rel).read_text()
    for name in ['rk817_codec_power_up', 'rk817_codec_power_down',
                 'rk817_playback_path_config', 'rk817_capture_path_config',
                 'rk817_digital_mute_dac', 'rk817_digital_mute_adc',
                 'rk817_digital_mute', 'rk817_codec_shutdown']:
        checks['legacy_body_byte_identical:' + name] = function(before, name) == function(after, name)
    patch = ''.join(''.join(difflib.unified_diff(
        (HERE / 'inputs-v1' / rel).read_text().splitlines(True),
        (HERE / 'source-v3' / rel).read_text().splitlines(True),
        fromfile='a/' + rel, tofile='b/' + rel)) for rel in candidate['files'])
    checks['patch_exact_three_source_delta'] = patch == (HERE / 'shared-io-private-v3.patch').read_text()
    checks['patch_sha'] = sha(patch.encode()) == candidate['patch_sha256']
    checks['generator_sha'] = sha((HERE / 'make-candidate.py').read_bytes()) == candidate['generator_sha256']
    new = json.loads((HERE / 'runs-new-v3/receipt.json').read_text())
    red = json.loads((HERE / 'runs-old-v3/receipt.json').read_text())
    checks['new_model_three_environments'] = new['status'] == 'EXPECTED_GREEN' and new['before'] == new['after'] and new['all_full_stdout_bytes_equal']
    checks['old_model_three_environments'] = red['status'] == 'EXPECTED_RED' and red['before'] == red['after'] and red['all_full_stdout_bytes_equal']
    for label in ['host', 'asan-ubsan', 'aarch64-qemu']:
        checks['new_fixed_count:' + label] = new['runs'][label]['observed'] == {'checks': 1111, 'passed': 1111, 'failed': 0}
        checks['old_fixed_count:' + label] = red['runs'][label]['observed'] == {'checks': 1111, 'passed': 25, 'failed': 1086}
    checks['no_PM_SLEEP_branch'] = new['no_pm_sleep_branch']['compile']['exit'] == 0 and new['no_pm_sleep_branch']['execution']['exit'] == 0
    receipt = {'scope': 'PRIVATE_THREE_SOURCE_DELTA_FINITE_AUDIT',
               'checks': checks, 'all_passed': all(checks.values()),
               'source_manifest_sha256': sha((HERE / 'source-manifest-v3.json').read_bytes()),
               'patch_sha256': candidate['patch_sha256'],
               'new_model_manifest_sha256': new['model_manifest_sha256'],
               'new_receipt_sha256': sha((HERE / 'runs-new-v3/receipt.json').read_bytes()),
               'old_receipt_sha256': sha((HERE / 'runs-old-v3/receipt.json').read_bytes()),
               'Kbuild_executed': False, 'START_authorized': False, 'board_tested': False}
    output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'passed': sum(checks.values()), 'total': len(checks),
                      'all_passed': receipt['all_passed'], 'patch_sha256': receipt['patch_sha256']}))
    return int(not receipt['all_passed'])


if __name__ == '__main__':
    raise SystemExit(main())
