#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Only format terminal PM handoff, retaining configuring until function exit."""
from pathlib import Path
import difflib
import json
from source_utils import function, replace, sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'


def main():
    inputs = json.loads((HERE / 'input-manifest.json').read_text())
    red_path = HERE / 'format-pm-red-v11-r2/result.json'
    red = json.loads(red_path.read_text())
    if not red['expected_red'] or red['source_sha256'] != inputs['cpu_v11_sha256'] or len(red['runs']) != 3 or any(
            not run['expected_red_reproduced'] or run['tests'] != {'total': 5, 'passed': 4}
            for run in red['runs'].values()):
        raise ValueError('Real v11 fmt/suspend race must be red in all environments first')
    prior_path = HERE / 'inputs/outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v11/source' / SOURCE
    prior = prior_path.read_text()
    if sha(prior_path.read_bytes()) != inputs['cpu_v11_sha256']:
        raise ValueError('Snapshot identity changed')
    revised = replace(prior, '\tbool configuring;\n',
                      '\tbool configuring;\n\tbool format_pm_release;\n')
    old_suspend = function(prior, 'i2s_checked_runtime_suspend')
    suspend = replace(old_suspend,
        '\telse if (i2s_tdm->configuring || i2s_tdm->started || !i2s_tdm->stop_proven)\n',
        '\telse if ((i2s_tdm->configuring && !i2s_tdm->format_pm_release) ||\n'
        '\t\t i2s_tdm->started || !i2s_tdm->stop_proven)\n')
    revised = replace(revised, old_suspend, suspend)
    old_fmt = function(prior, 'i2s_checked_set_fmt')
    fmt = replace(old_fmt, 'put:\n\tput_ret = pm_runtime_put(dev);',
        'put:\n'
        '\t/* All format MMIO is finished. Publish any first error before PM.\n'
        '\t * Keep configuring set: other commands and destruction still reject\n'
        '\t * this in-flight function, while a successful terminal handoff lets\n'
        '\t * the asynchronous suspend drain IRQs and release our MCLK refs.\n'
        '\t */\n'
        '\tspin_lock_irqsave(&i2s_tdm->lock, flags);\n'
        '\tif (!ret && i2s_tdm->runtime_error)\n'
        '\t\tret = i2s_tdm->runtime_error;\n'
        '\ti2s_checked_error_locked(i2s_tdm, ret);\n'
        '\ti2s_tdm->format_pm_release = !ret;\n'
        '\tspin_unlock_irqrestore(&i2s_tdm->lock, flags);\n'
        '\tput_ret = pm_runtime_put(dev);')
    fmt = replace(fmt, '\ti2s_tdm->configuring = false;\n',
                  '\ti2s_tdm->format_pm_release = false;\n\ti2s_tdm->configuring = false;\n')
    revised = replace(revised, old_fmt, fmt)
    out = HERE / 'source'
    out.mkdir(exist_ok=False)
    target = out / SOURCE
    target.parent.mkdir(parents=True)
    target.write_text(revised)
    pristine_path = ROOT / 'third_party/linux-rk3588' / SOURCE
    pristine = pristine_path.read_text()
    if sha(pristine_path.read_bytes()) != inputs['protected_sha256'][pristine_path.relative_to(ROOT).as_posix()]:
        raise ValueError('Protected pristine source changed')
    for name, start in [('delta-v11-v12.patch', prior), ('i2s-lifecycle-v12.patch', pristine)]:
        patch = ''.join(difflib.unified_diff(start.splitlines(keepends=True), revised.splitlines(keepends=True),
                                           fromfile='a/' + SOURCE, tofile='b/' + SOURCE))
        (out / name).write_text(patch)
    manifest = {'version': 12, 'source_sha256': sha(target.read_bytes()),
                'prior_v11_sha256': inputs['cpu_v11_sha256'], 'pristine_sha256': sha(pristine_path.read_bytes()),
                'delta_patch_sha256': sha((out / 'delta-v11-v12.patch').read_bytes()),
                'patch_sha256': sha((out / 'i2s-lifecycle-v12.patch').read_bytes()),
                'modified_functions': ['i2s_checked_runtime_suspend', 'i2s_checked_set_fmt'],
                'added_private_field': 'bool format_pm_release',
                'function_sha256': {'i2s_checked_runtime_suspend': sha(suspend.encode()),
                                    'i2s_checked_set_fmt': sha(fmt.encode())},
                'prior_red_receipt_sha256': sha(red_path.read_bytes()),
                'sysfs_format_changed': False, 'other_gates_and_teardown_unchanged': True,
                'v11_zero_request_and_hw_params_unchanged': True,
                'scope': 'Only successful set_fmt after all MMIO may hand off to unchanged suspend hardware operations while configuring remains true. Format failure is latched before PM put. All exits clear the private handoff; sticky is never cleared.',
                'board_tested': False, 'full_image_built': False, 'published': False,
                'audio_start_allowed': False}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({key: manifest[key] for key in ['source_sha256', 'delta_patch_sha256', 'patch_sha256']}))


if __name__ == '__main__':
    main()
