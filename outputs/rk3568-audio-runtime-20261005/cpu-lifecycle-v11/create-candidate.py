#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Apply only cache-reset admission and zero-request hw_params guard."""
from pathlib import Path
import difflib
import json
from source_utils import function, replace, sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'


def main():
    inputs = json.loads((HERE / 'input-manifest.json').read_text())
    red = json.loads((HERE / 'shutdown-red-v10/result.json').read_text())
    if not red['expected_red'] or red['source_sha256'] != inputs['cpu_v10_sha256'] or len(red['runs']) != 3 or any(
            not item['expected_red_reproduced'] or item['tests'] != {'total': 4, 'passed': 3}
            for item in red['runs'].values()):
        raise ValueError('Actual old CPU plus real simple shutdown must fail first')
    base_path = HERE / 'inputs/outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10' / SOURCE
    original = base_path.read_text()
    if sha(base_path.read_bytes()) != inputs['cpu_v10_sha256']:
        raise ValueError('Frozen v10 source mismatch')
    old_sysclk = function(original, 'rockchip_i2s_tdm_set_sysclk')
    sysclk = replace(old_sysclk,
        'if ((stream != SNDRV_PCM_STREAM_PLAYBACK && stream != SNDRV_PCM_STREAM_CAPTURE) || !freq)',
        'if (stream != SNDRV_PCM_STREAM_PLAYBACK && stream != SNDRV_PCM_STREAM_CAPTURE)')
    sysclk = replace(sysclk,
        '\t\tret = i2s_checked_gate_locked(i2s_tdm);\n\t\tif (!ret) {',
        '\t\tret = i2s_checked_gate_locked(i2s_tdm);\n'
        '\t\t/* Machine shutdown resets cached requests after DAI STOP/IRQ drain. */\n'
        '\t\tif (!ret && !freq &&\n'
        '\t\t    (!i2s_tdm->stop_proven || !i2s_tdm->irq_drained ||\n'
        '\t\t     READ_ONCE(i2s_tdm->substreams[0]) || READ_ONCE(i2s_tdm->substreams[1])))\n'
        '\t\t\tret = -EBUSY;\n'
        '\t\t/* Zero only clears the shared TRCM request; never clk_set_rate(0). */\n'
        '\t\tif (!ret) {')
    old_params = function(original, 'i2s_checked_hw_params')
    params = replace(old_params,
        '\tret = i2s_checked_gate_locked(i2s_tdm);\n\tif (!ret)\n\t\ti2s_tdm->configuring = true;',
        '\tret = i2s_checked_gate_locked(i2s_tdm);\n'
        '\t/* A shutdown cache reset requires a new positive sysclk request first. */\n'
        '\tif (!ret && (!i2s_tdm->mclk_tx_freq || !i2s_tdm->mclk_rx_freq))\n'
        '\t\tret = -EINVAL;\n'
        '\tif (!ret)\n\t\ti2s_tdm->configuring = true;')
    revised = replace(replace(original, old_sysclk, sysclk), old_params, params)
    out = HERE / 'source'
    out.mkdir(exist_ok=False)
    target = out / SOURCE
    target.parent.mkdir(parents=True)
    target.write_text(revised)
    pristine_path = ROOT / 'third_party/linux-rk3588' / SOURCE
    pristine = pristine_path.read_text()
    if sha(pristine_path.read_bytes()) != inputs['protected_sha256'][pristine_path.relative_to(ROOT).as_posix()]:
        raise ValueError('Original kernel source changed')
    delta = ''.join(difflib.unified_diff(original.splitlines(keepends=True), revised.splitlines(keepends=True),
                                       fromfile='a/' + SOURCE, tofile='b/' + SOURCE))
    patch = ''.join(difflib.unified_diff(pristine.splitlines(keepends=True), revised.splitlines(keepends=True),
                                       fromfile='a/' + SOURCE, tofile='b/' + SOURCE))
    (out / 'delta-v10-v11.patch').write_text(delta)
    (out / 'i2s-lifecycle-v11.patch').write_text(patch)
    manifest = {'version': 11, 'board_tested': False, 'published': False,
                'full_image_built': False, 'audio_start_allowed': False,
                'source_sha256': sha(target.read_bytes()), 'prior_v10_sha256': inputs['cpu_v10_sha256'],
                'pristine_sha256': sha(pristine_path.read_bytes()),
                'delta_patch_sha256': sha((out / 'delta-v10-v11.patch').read_bytes()),
                'patch_sha256': sha((out / 'i2s-lifecycle-v11.patch').read_bytes()),
                'modified_functions': ['rockchip_i2s_tdm_set_sysclk', 'i2s_checked_hw_params'],
                'function_sha256': {'rockchip_i2s_tdm_set_sysclk': sha(sysclk.encode()),
                                    'i2s_checked_hw_params': sha(params.encode())},
                'legacy_sysclk_and_hw_params_branches_changed': False,
                'new_hardware_operations_in_zero_set_sysclk': False,
                'zero_does_not_clear_sticky_or_release_clock_references': True,
                'zero_admission': 'Original checked gate plus STOP proven, IRQ drained and both substreams absent; shared TX/RX cache reset under same lock',
                'missing_nonzero_request_hw_params': 'EINVAL before configuring, clk_set_rate, PM or MMIO; next real simple hw_params reestablishes both requests'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'source_sha256': manifest['source_sha256'], 'delta_patch_sha256': manifest['delta_patch_sha256'],
                      'patch_sha256': manifest['patch_sha256'], 'modified_functions': manifest['modified_functions']}))


if __name__ == '__main__':
    main()
