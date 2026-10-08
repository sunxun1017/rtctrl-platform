#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Lock ordinary production inputs and extract a bounded caller-chain baseline."""
import importlib.util
import argparse
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CPU_V12 = ROOT / 'outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v12'
PRIOR = CPU_V12 / 'inputs/outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v11'
KERNEL = PRIOR / 'inputs/.deps/kernel-source/aiot-3568pq-audio-v1'
C3 = ROOT / 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/full-replay'
EXPECTED_CPU = '7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', type=int, required=True)
    args = parser.parse_args()
    if args.version < 3:
        parser.error('fresh generation >= 3; preserve failed v1/v2')
    output = HERE / ('model-v' + str(args.version))
    output.mkdir(exist_ok=False)
    inputs = HERE / ('inputs-v' + str(args.version))
    inputs.mkdir(exist_ok=False)
    util_path = CPU_V12 / 'source_utils.py'
    spec = importlib.util.spec_from_file_location('source_utils', util_path)
    util = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(util)
    sha, function, declaration = util.sha, util.function, util.declaration
    review_path = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/full-duplex-review-v1/input-manifest.json'
    review = json.loads(review_path.read_text())
    locked = {}

    def lock(path):
        path = Path(path)
        if not stat.S_ISREG(path.lstat().st_mode) or path.is_symlink():
            raise ValueError(f'not ordinary: {path}')
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        digest = sha(data)
        old = review['inputs'].get(relative)
        if old and digest != old['sha256']:
            raise ValueError(f'review input changed: {relative}')
        destination = inputs / (sha(relative.encode())[:12] + '-' + path.name)
        destination.write_bytes(data)
        locked[relative] = {'sha256': digest, 'size': len(data),
                            'snapshot': destination.relative_to(HERE).as_posix(),
                            'ordinary': True, 'review_sha_checked': bool(old)}
        return data.decode()

    sources = {
        'cpu': lock(CPU_V12 / 'source/sound/soc/rockchip/rockchip_i2s_tdm.c'),
        'simple': lock(ROOT / '.deps/kernel-source/aiot-3568pq-audio-v2/sound/soc/generic/simple-card-utils.c'),
        'codec': lock(C3 / 'sound/soc/codecs/rk817_codec.c'),
        'dai': lock(C3 / 'sound/soc/soc-dai.c'),
        'component': lock(C3 / 'sound/soc/soc-component.c'),
        'pcm': lock(C3 / 'sound/soc/soc-pcm.c'),
        'link': lock(ROOT / '.deps/kernel-source/aiot-3568pq-audio-v3/sound/soc/soc-link.c'),
    }
    if sha(sources['cpu'].encode()) != EXPECTED_CPU:
        raise ValueError('wrong CPU v12')
    lock(review_path)
    lock(util_path)
    for proof in ['sound/soc/soc-compress.c', 'include/linux/pm_runtime.h',
                  'drivers/base/power/runtime.c', 'include/sound/soc-component.h']:
        lock(ROOT / '.deps/kernel-source/aiot-3568pq-audio-v3' / proof)
    (output / 'source_utils.py').write_bytes(util_path.read_bytes())
    shim = lock(PRIOR / 'inputs/outputs/rk3568-i2s-lifecycle-20261005/test-params-shim.h')
    shim = shim.replace('struct snd_pcm_substream { int stream; long wait_time; };',
        'struct snd_pcm_runtime;\nstruct snd_pcm_substream { int stream; long wait_time; '
        'struct snd_pcm_runtime *runtime; void *private_data; bool pm_held; bool component_opened; };')
    shim = shim.replace('struct device { void *data; int usage; };',
                        'struct device { void *data; int usage; int inject_get_error; '
                        'unsigned int get_calls, noidle_puts, auto_puts; };')
    shim = shim.replace('dev->usage++; return pm_error;',
                        'dev->usage++; dev->get_calls++; return dev->inject_get_error ? dev->inject_get_error : pm_error;')
    noidle = function(shim, 'pm_runtime_put_noidle')
    shim = shim.replace(noidle, 'static void pm_runtime_put_noidle(struct device *dev);')
    shim += '\n#include "model-extra-primitives.h"\n'
    (output / 'test-params-shim.h').write_text(shim)
    for name, relative in [('asound.h', 'include/uapi/sound/asound.h'),
                           ('rockchip_i2s_tdm.h', 'sound/soc/rockchip/rockchip_i2s_tdm.h')]:
        text = lock(KERNEL / relative)
        (output / name).write_text(text)
    headers = {p: lock(KERNEL / p) for p in [
        'include/sound/pcm.h', 'include/sound/pcm_params.h', 'include/sound/soc-dai.h',
        'include/sound/dmaengine_pcm.h', 'include/uapi/sound/asoc.h', 'include/sound/simple_card_utils.h']}
    soc = lock(ROOT / '.deps/kernel-source/aiot-3568pq-audio-v3/include/sound/soc.h')
    sources['soc-header'] = soc
    abi = declaration(headers['include/sound/dmaengine_pcm.h'], 'struct', 'snd_dmaengine_dai_dma_data') + '\n'
    abi += declaration(headers['include/sound/soc-dai.h'], 'struct', 'snd_soc_dai') + '\n'
    for name in ['snd_soc_dai_get_drvdata', 'snd_soc_dai_get_dma_data']:
        abi += function(headers['include/sound/soc-dai.h'], name) + '\n'
    for path, names in [('include/sound/pcm.h', ['hw_param_mask_c', 'hw_param_interval_c', 'params_channels', 'params_rate']),
                        ('include/sound/pcm_params.h', ['snd_mask_min', 'params_format'])]:
        abi += '\n'.join(function(headers[path], name) for name in names) + '\n'
    abi += declaration(headers['include/sound/simple_card_utils.h'], 'struct', 'asoc_simple_dai') + '\n'
    (output / 'actual-abi.h').write_text(abi)
    formats = ''.join(line for line in headers['include/uapi/sound/asoc.h'].splitlines(True)
                      if line.startswith('#define SND_SOC_DAI_FORMAT_'))
    formats += ''.join(line for line in headers['include/sound/soc-dai.h'].splitlines(True)
                      if line.startswith(('#define SND_SOC_DAIFMT_', '#define SND_SOC_CLOCK_')))
    formats += ''.join(line for line in headers['include/sound/pcm.h'].splitlines(True)
                      if line.startswith('#define SNDRV_PCM_TRIGGER_'))
    (output / 'actual-formats.h').write_text(formats)
    macros = ''
    lines = soc.splitlines(True)
    for name in ['for_each_rtd_dais', 'for_each_rtd_components']:
        index = next(i for i, line in enumerate(lines) if line.startswith('#define ' + name + '('))
        start = index
        while lines[index].rstrip().endswith('\\'):
            index += 1
        macros += ''.join(lines[start:index + 1])
    for source, prefix in [('dai', 'soc_dai_mark_'), ('link', 'soc_link_mark_'), ('component', 'soc_component_mark_')]:
        macros += ''.join(line for line in sources[source].splitlines(True)
                          if line.startswith('#define ' + prefix))
    pcm_lines = headers['include/sound/pcm.h'].splitlines(True)
    index = next(i for i, line in enumerate(pcm_lines) if line.startswith('#define for_each_pcm_streams('))
    start = index
    while pcm_lines[index].rstrip().endswith('\\'):
        index += 1
    macros += ''.join(pcm_lines[start:index + 1])
    (output / 'actual-iteration-mark-macros.h').write_text(macros)
    names = {
        'cpu': ['i2s_checked_first_error', 'i2s_checked_error_locked', 'i2s_checked_gate_locked',
                'i2s_checked_params_dirty', 'i2s_checked_params_trcm', 'i2s_checked_set_fmt', 'to_info',
                'rockchip_i2s_tdm_mclk_reparent', 'rockchip_i2s_tdm_set_mclk',
                'rockchip_i2s_tdm_params_channels', 'i2s_checked_hw_params', 'is_params_dirty',
                'rockchip_i2s_tdm_params_trcm', 'rockchip_i2s_tdm_set_fmt',
                'rockchip_i2s_tdm_hw_params', 'rockchip_i2s_tdm_set_sysclk', 'rockchip_dai_tdm_slot',
                'i2s_checked_irq_locked', 'i2s_checked_dma_locked', 'i2s_checked_clear_locked',
                'i2s_checked_stop_locked', 'i2s_checked_start_locked', 'i2s_checked_trigger',
                'rockchip_i2s_tdm_trigger', 'i2s_checked_component_trigger',
                'rockchip_i2s_tdm_startup', 'rockchip_i2s_tdm_shutdown', 'i2s_checked_prepare'],
        'codec': ['rk817_set_dai_sysclk'],
        'dai': ['_soc_dai_ret', 'snd_soc_dai_set_sysclk', 'snd_soc_dai_startup',
                'snd_soc_dai_shutdown', 'snd_soc_pcm_dai_trigger', 'snd_soc_dai_action', 'snd_soc_dai_active'],
        'component': ['_soc_component_ret', 'snd_soc_pcm_component_trigger',
                      'snd_soc_pcm_component_pm_runtime_get', 'snd_soc_pcm_component_pm_runtime_put'],
        'simple': ['asoc_simple_clk_enable', 'asoc_simple_clk_disable', 'asoc_simple_startup',
                   'asoc_simple_shutdown', 'asoc_simple_set_clk_rate', 'asoc_simple_hw_params'],
        'link': ['_soc_link_ret', 'snd_soc_link_startup', 'snd_soc_link_shutdown', 'snd_soc_link_trigger'],
        'pcm': ['soc_pcm_clean', 'soc_pcm_open', 'soc_pcm_trigger', 'snd_soc_runtime_action', 'soc_pcm_apply_symmetry'],
        'soc-header': ['snd_soc_runtime_activate', 'snd_soc_runtime_deactivate'],
    }
    units = {}
    prototypes = ''
    functions = ''
    for kind, members in names.items():
        bodies = []
        for name in members:
            body = function(sources[kind], name)
            units[kind + ':' + name] = {'sha256': sha(body.encode()),
                'source_group': kind, 'line': sources[kind][:sources[kind].index(body)].count('\n') + 1}
            prototypes += body[:body.index('{')].strip() + ';\n'
            bodies.append(body)
        text = '\n\n'.join(bodies) + '\n'
        (output / ('actual-' + kind + '-functions.c')).write_text(text)
        functions += text
    cpu_types = '\n'.join(declaration(sources['cpu'], 'struct', n)
                          for n in ['txrx_config', 'rk_i2s_soc_data', 'rk_i2s_tdm_dev']) + '\n'
    (output / 'actual-cpu-types.h').write_text(cpu_types)
    for name in ['model-extra-primitives.h', 'model-glue.h', 'test-caller-chain.c']:
        (output / name).write_bytes((HERE / name).read_bytes())
    unit = '#include "test-params-shim.h"\n#include "actual-abi.h"\n#include "actual-cpu-types.h"\n'
    unit += '#include "model-glue.h"\n' + prototypes + '\n' + functions
    unit += '\n#include "test-caller-chain.c"\n'
    (output / 'unit.c').write_text(unit)
    manifest = {'schema': 'rk3568-full-duplex-baseline-input-v1', 'CPU_sha256': EXPECTED_CPU,
                'input_files': locked, 'production_functions': units,
                'generated_unit_sha256': sha(unit.encode()),
                'review_only_no_production_changes': True, 'board_tested': False,
                'model_boundaries': ['regmap/CCF/kernel PM scheduling/ALSA constraint API side effects',
                    'actual runtime and DAI activation/active/action and PM wrappers are extracted',
                    'platform DMA trigger/open/close is an explicit API side-effect model',
                    'codec trigger injection is a model; only sysclk setter is production',
                    'not full soc_pcm_hw_params, DAPM, PL330 or kernel ABI']}
    (output / 'input-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'prepare-snapshot.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'inputs': len(locked), 'real_functions': len(units), 'unit_sha256': sha(unit.encode())}))


if __name__ == '__main__':
    main()
