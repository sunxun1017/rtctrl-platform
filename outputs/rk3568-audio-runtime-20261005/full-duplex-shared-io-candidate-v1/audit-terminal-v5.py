#!/usr/bin/env python3
"""Narrow final identity and observed-result audit; no compiler or board work."""
import difflib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SDK = HERE.parents[2] / '.deps/kernel-source/aiot-3568pq-audio-v4'
PARAMS = HERE.parent / 'full-duplex-params-candidate-v1'
spec = importlib.util.spec_from_file_location('source_utils', PARAMS / 'model-v4/source_utils.py')
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)
sha, function = utils.sha, utils.function


def main():
    checks = {}
    manifest_path = HERE / 'source-manifest-v5.json'
    manifest = json.loads(manifest_path.read_text())
    patches = []
    changed = []
    for rel, record in manifest['files'].items():
        before_path = SDK / rel if rel == 'include/sound/soc.h' else HERE / 'source-v3' / rel
        after_path = HERE / 'source-v5' / rel
        before, after = before_path.read_bytes(), after_path.read_bytes()
        checks['baseline_identity:' + rel] = sha(before) == record['baseline_sha256']
        checks['candidate_identity:' + rel] = sha(after) == record['candidate_sha256']
        if before != after:
            changed.append(rel)
            patches.append(''.join(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                                                      fromfile='a/' + rel, tofile='b/' + rel)))
    patch = (HERE / 'terminal-private-v5.patch').read_bytes()
    checks['exact_four_file_increment'] = changed == ['include/sound/soc.h', 'sound/soc/codecs/rk817_codec.c',
                                                     'sound/soc/rockchip/rockchip_i2s_tdm.c', 'sound/soc/soc-core.c']
    checks['patch_exact'] = ''.join(patches).encode() == patch
    checks['patch_sha256'] = sha(patch) == manifest['patch_sha256']
    checks['v3_source_manifest_preserved'] = sha((HERE / 'source-manifest-v3.json').read_bytes()) == '9c279d2b79415fa4f11e163c723542bde9fead432aa56e29358a80140ab06036'
    checks['v4_source_manifest_preserved'] = sha((HERE / 'source-manifest-v4.json').read_bytes()) == 'f4be43540800f06fc85d520b0e8962dc3e855b446489acd122add25fe5c5007c'
    codec_before = (HERE / 'source-v3/sound/soc/codecs/rk817_codec.c').read_text()
    codec_after = (HERE / 'source-v5/sound/soc/codecs/rk817_codec.c').read_text()
    for name in ['rk817_codec_power_up', 'rk817_codec_power_down', 'rk817_playback_path_config',
                 'rk817_capture_path_config', 'rk817_digital_mute_dac', 'rk817_digital_mute_adc',
                 'rk817_digital_mute', 'rk817_codec_shutdown']:
        checks['legacy_exact:' + name] = function(codec_before, name) == function(codec_after, name)
    core_before = (HERE / 'source-v3/sound/soc/soc-core.c').read_text()
    core_after = (HERE / 'source-v5/sound/soc/soc-core.c').read_text()
    for name in ['soc_remove_component', 'soc_cleanup_card_resources', 'snd_soc_unbind_card',
                 'snd_soc_unregister_card', 'snd_soc_del_component_unlocked', 'snd_soc_unregister_component']:
        checks['original_framework_body_exact:' + name] = function(core_before, name) == function(core_after, name)
    checks['only_codec_platform_shutdown_calls_helper'] = codec_after.count('snd_soc_component_shutdown_card(') == 1 and \
        'snd_soc_component_shutdown_card(' in function(codec_after, 'rk817_platform_shutdown')
    for side, run_dir, wanted in [('old', 'runs-terminal-framework-old-v1', (1471, 1260, 211)),
                                 ('new', 'runs-terminal-framework-new-v2', (1471, 1471, 0))]:
        receipt = json.loads((HERE / run_dir / 'receipt.json').read_text())
        checks[side + ':model_inputs_before_after_equal'] = receipt['before'] == receipt['after']
        checks[side + ':complete_stdout_equal'] = receipt['all_full_stdout_bytes_equal']
        for label in ['host', 'asan-ubsan', 'aarch64-qemu']:
            run = receipt['runs'][label]
            checks[side + ':' + label + ':compile_run_checks'] = run['compile']['exit'] == 0 and \
                run['execution']['exit'] == (1 if side == 'old' else 0) and \
                tuple(run['observed'][key] for key in ['checks', 'passed', 'failed']) == wanted and \
                run['expected_scope_verified'] and not run['execution']['stderr_bytes']
        checks[side + ':no_PM_SLEEP_compile_run'] = receipt['no_pm_sleep_branch']['compile']['exit'] == 0 and \
            receipt['no_pm_sleep_branch']['execution']['exit'] == 0
    out = HERE / 'terminal-audit-v5.json'
    out.write_text(json.dumps({
        'scope': 'FINITE_TERMINAL_SOURCE_IDENTITY_AND_ACTUAL_MODEL_RESULT_AUDIT',
        'checks': checks, 'all_passed': all(checks.values()),
        'source_manifest_sha256': sha(manifest_path.read_bytes()), 'patch_sha256': sha(patch),
        'new_model_manifest_sha256': sha((HERE / 'model-terminal-framework-new-v2/manifest.json').read_bytes()),
        'new_receipt_sha256': sha((HERE / 'runs-terminal-framework-new-v2/receipt.json').read_bytes()),
        'old_receipt_sha256': sha((HERE / 'runs-terminal-framework-old-v1/receipt.json').read_bytes()),
        'agent_Kbuild_executed': False, 'board_tested': False, 'START_authorized': False,
    }, indent=2) + '\n')
    print(json.dumps({'checks': len(checks), 'passed': sum(checks.values()), 'all_passed': all(checks.values())}))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
