#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract real CPU/ASoC/simple/codec functions; execute synthetic API models."""
from pathlib import Path
import argparse
import json
import subprocess
from source_utils import declaration, function, sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'outputs/rk3568-i2s-lifecycle-20261005'
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
FIXTURE = HERE / 'inputs/outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v11/inputs'
KERNEL_COPY = FIXTURE / '.deps/kernel-source/aiot-3568pq-audio-v1'


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--red-v10', action='store_true')
    modes.add_argument('--params-regression', action='store_true')
    args = parser.parse_args()
    source_path = FIXTURE / 'outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10' / SOURCE if args.red_v10 else HERE / 'source' / SOURCE
    source = source_path.read_text()
    output = HERE / ('shutdown-red-v10' if args.red_v10 else 'params-regression-v12' if args.params_regression else 'shutdown-green-v12')
    output.mkdir(exist_ok=False)
    (output / 'runner-snapshot.py').write_bytes(Path(__file__).read_bytes())
    for filename in ['test-params-shim.h', 'test-params-main.c']:
        (output / filename).write_bytes((FIXTURE / 'outputs/rk3568-i2s-lifecycle-20261005' / filename).read_bytes())
    for filename, relative in [('asound.h', 'include/uapi/sound/asound.h'), ('rockchip_i2s_tdm.h', 'sound/soc/rockchip/rockchip_i2s_tdm.h')]:
        (output / filename).write_bytes((KERNEL_COPY / relative).read_bytes())
    headers = {name: (KERNEL_COPY / name).read_text() for name in [
        'include/sound/pcm.h', 'include/sound/pcm_params.h', 'include/sound/soc-dai.h',
        'include/sound/dmaengine_pcm.h', 'include/uapi/sound/asoc.h', 'include/sound/simple_card_utils.h']}
    abi = declaration(headers['include/sound/dmaengine_pcm.h'], 'struct', 'snd_dmaengine_dai_dma_data') + '\n'
    abi += declaration(headers['include/sound/soc-dai.h'], 'struct', 'snd_soc_dai') + '\n'
    for name in ['snd_soc_dai_get_drvdata', 'snd_soc_dai_get_dma_data']:
        abi += function(headers['include/sound/soc-dai.h'], name) + '\n'
    for header, names in [('include/sound/pcm.h', ['hw_param_mask_c', 'hw_param_interval_c', 'params_channels', 'params_rate']),
                          ('include/sound/pcm_params.h', ['snd_mask_min', 'params_format'])]:
        abi += '\n'.join(function(headers[header], name) for name in names) + '\n'
    defines = ''.join(line for line in headers['include/uapi/sound/asoc.h'].splitlines(True) if line.startswith('#define SND_SOC_DAI_FORMAT_'))
    defines += ''.join(line for line in headers['include/sound/soc-dai.h'].splitlines(True) if line.startswith(('#define SND_SOC_DAIFMT_', '#define SND_SOC_CLOCK_')))
    (output / 'actual-abi.h').write_text(abi)
    (output / 'actual-formats.h').write_text(defines)
    cpu_names = ['i2s_checked_error_locked', 'i2s_checked_gate_locked', 'i2s_checked_params_dirty',
                 'i2s_checked_params_trcm', 'i2s_checked_set_fmt', 'to_info',
                 'rockchip_i2s_tdm_mclk_reparent', 'rockchip_i2s_tdm_set_mclk',
                 'rockchip_i2s_tdm_params_channels', 'i2s_checked_hw_params', 'is_params_dirty',
                 'rockchip_i2s_tdm_params_trcm', 'rockchip_i2s_tdm_set_fmt',
                 'rockchip_i2s_tdm_hw_params', 'rockchip_i2s_tdm_set_sysclk', 'rockchip_dai_tdm_slot']
    bodies = {name: function(source, name) for name in cpu_names}
    declarations = '\n'.join(declaration(source, 'struct', name) for name in ['txrx_config', 'rk_i2s_soc_data', 'rk_i2s_tdm_dev'])
    actual_cpu = '#define HAVE_CHECKED 1\n' + declarations + '\n' + '\n\n'.join(bodies.values()) + '\n'
    caller_sources = {'simple': (KERNEL_COPY / 'sound/soc/generic/simple-card-utils.c').read_text(),
                      'dai': (KERNEL_COPY / 'sound/soc/soc-dai.c').read_text(),
                      'codec': (KERNEL_COPY / 'sound/soc/codecs/rk817_codec.c').read_text()}
    callers = {'rk817_set_dai_sysclk': function(caller_sources['codec'], 'rk817_set_dai_sysclk'),
               'snd_soc_dai_set_sysclk': function(caller_sources['dai'], 'snd_soc_dai_set_sysclk')}
    for name in ['asoc_simple_clk_disable', 'asoc_simple_shutdown', 'asoc_simple_set_clk_rate', 'asoc_simple_hw_params']:
        callers[name] = function(caller_sources['simple'], name)
    (output / 'actual-cpu-functions.c').write_text(actual_cpu)
    (output / 'actual-caller-functions.c').write_text('\n\n'.join(callers.values()) + '\n')
    for filename in ['simple-model-glue.h', 'test-sysclk-main.c']:
        (output / filename).write_bytes((HERE / filename).read_bytes())
    unit = output / 'unit.c'
    unit.write_text('#include "test-params-shim.h"\n#include "actual-abi.h"\n' + actual_cpu + '\n' +
                    declaration(headers['include/sound/simple_card_utils.h'], 'struct', 'asoc_simple_dai') + '\n' +
                    '#include "simple-model-glue.h"\n' + '\n\n'.join(callers.values()) + '\n#include "test-sysclk-main.c"\n')
    if args.params_regression:
        unit.write_text('#include "test-params-shim.h"\n#include "actual-abi.h"\n' + actual_cpu + '\n#include "test-params-main.c"\n')
    receipt = {'model_only': True, 'board_tested': False, 'expected_red': args.red_v10,
               'source_sha256': sha(source_path.read_bytes()),
               'cpu_functions_sha256': {name: sha(body.encode()) for name, body in bodies.items()},
               'caller_functions_sha256': {name: sha(body.encode()) for name, body in callers.items()},
               'test_sha256': sha(Path(__file__).read_bytes()),
               'main_sha256': sha((HERE / 'test-sysclk-main.c').read_bytes()),
               'glue_sha256': sha((HERE / 'simple-model-glue.h').read_bytes()),
               'boundary': 'Byte-exact CPU set_sysclk/gate/hw_params, real simple shutdown/next hw_params, real DAI dispatch and codec cache setter. Post-CPU-shutdown STOP/IRQ/open fields are synthetic; CCF/regmap/PM/ASoC helpers are models, not complete close, hardware, or kernel ABI.',
               'runs': {}}
    for label, compiler, flags, prefix in [
            ('host', 'gcc', [], []),
            ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'], []),
            ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-static'], [str(ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static')])]:
        binary = output / ('sysclk-' + label)
        argv = [compiler, '-std=gnu11', '-O0', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', '-Wno-unused-function', '-pthread', *flags, str(unit), '-o', str(binary)]
        compiled = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (output / (label + '-compile.stdout')).write_text(compiled.stdout)
        (output / (label + '-compile.stderr')).write_text(compiled.stderr)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)
        executed = subprocess.run(prefix + [str(binary)] + (['red-v10'] if args.red_v10 else []), capture_output=True, text=True, timeout=60)
        (output / (label + '.stdout')).write_text(executed.stdout)
        (output / (label + '.stderr')).write_text(executed.stderr)
        tests = json.loads(executed.stdout.splitlines()[-1])
        failures = [line.split(' ')[1] for line in executed.stdout.splitlines() if line.startswith('SYSCLK_CHECK ') and line.endswith(' 0')]
        expected_failures = ['simple_shutdown_clears_shared_requests'] if args.red_v10 else []
        valid = failures == expected_failures and executed.returncode == (1 if args.red_v10 else 0)
        if args.params_regression:
            valid = valid and tests['total'] == tests['passed']
        record = {'compile_argv': argv, 'exit': executed.returncode, 'tests': tests,
                  'failures': failures, 'expected_red_reproduced': args.red_v10 and valid,
                  'binary_sha256': sha(binary.read_bytes()),
                  'stdout_sha256': sha(executed.stdout.encode()), 'stderr_sha256': sha(executed.stderr.encode())}
        receipt['runs'][label] = record
        if not valid:
            (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
            raise RuntimeError(f'{label}: {failures}; {executed.stderr}')
    (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'expected_red': args.red_v10, 'runs': {name: item['tests'] for name, item in receipt['runs'].items()}}))


if __name__ == '__main__':
    main()
