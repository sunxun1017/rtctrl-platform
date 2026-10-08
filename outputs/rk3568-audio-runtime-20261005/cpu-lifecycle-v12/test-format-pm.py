#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute extracted production fmt/suspend/gate/startup/teardown in API models."""
from pathlib import Path
import argparse
import json
import subprocess
from source_utils import declaration, function, sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = HERE / 'inputs/outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v11'
SOURCE = 'sound/soc/rockchip/rockchip_i2s_tdm.c'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--red-v11', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    source_path = (PRIOR / 'source' if args.red_v11 else HERE / 'source') / SOURCE
    source = source_path.read_text()
    output = HERE / (args.output or ('format-pm-red-v11' if args.red_v11 else 'format-pm-green-v12'))
    output.mkdir(exist_ok=False)
    v11_inputs = PRIOR / 'inputs'
    old = v11_inputs / 'outputs/rk3568-i2s-lifecycle-20261005'
    kernel = v11_inputs / '.deps/kernel-source/aiot-3568pq-audio-v1'
    for name, path in [('asound.h', kernel / 'include/uapi/sound/asound.h'),
                       ('rockchip_i2s_tdm.h', kernel / 'sound/soc/rockchip/rockchip_i2s_tdm.h')]:
        (output / name).write_bytes(path.read_bytes())
    # Keep the mature shim's layouts and transform only its PM/register hooks.
    shim = (old / 'test-params-shim.h').read_text()
    shim = shim.replace('struct device { void *data; int usage; };',
                        'struct device { void *data; int usage; int status; int core_error; };')
    shim = shim.replace('struct regmap { unsigned int hw[64]; unsigned int cache[64]; };',
                        'struct regmap { unsigned int hw[64]; unsigned int cache[64]; bool cache_only; };')
    for name in ['pm_runtime_get_sync', 'pm_runtime_put', 'pm_runtime_put_noidle', 'regmap_update_bits']:
        body = function(shim, name)
        prototype = body[:body.index('{')].strip() + ';'
        shim = shim.replace(body, prototype)
    shim = shim.replace('#endif\n', '\n#include "pm-model-declarations.h"\n#endif\n')
    (output / 'test-params-shim.h').write_text(shim)
    headers = {name: (kernel / name).read_text() for name in [
        'include/sound/soc-dai.h', 'include/sound/dmaengine_pcm.h', 'include/uapi/sound/asoc.h']}
    abi = declaration(headers['include/sound/dmaengine_pcm.h'], 'struct', 'snd_dmaengine_dai_dma_data') + '\n'
    abi += declaration(headers['include/sound/soc-dai.h'], 'struct', 'snd_soc_dai') + '\n'
    abi += function(headers['include/sound/soc-dai.h'], 'snd_soc_dai_get_drvdata') + '\n'
    defines = ''.join(line for line in headers['include/uapi/sound/asoc.h'].splitlines(True)
                      if line.startswith('#define SND_SOC_DAI_FORMAT_'))
    defines += ''.join(line for line in headers['include/sound/soc-dai.h'].splitlines(True)
                       if line.startswith(('#define SND_SOC_DAIFMT_', '#define SND_SOC_CLOCK_')))
    defines += ''.join(line for line in (kernel / 'include/sound/pcm.h').read_text().splitlines(True)
                      if line.startswith('#define SNDRV_PCM_TRIGGER_'))
    (output / 'actual-abi.h').write_text(abi)
    (output / 'actual-formats.h').write_text(defines)
    names = ['i2s_checked_first_error', 'i2s_checked_error_locked', 'i2s_checked_gate_locked',
             'i2s_checked_runtime_suspend', 'i2s_checked_set_fmt',
             'i2s_checked_component_trigger', 'rockchip_i2s_tdm_startup',
             'i2s_checked_pm_disable', 'i2s_checked_quiesce']
    bodies = {name: function(source, name) for name in names}
    declarations = '\n'.join(declaration(source, 'struct', name)
                             for name in ['txrx_config', 'rk_i2s_soc_data', 'rk_i2s_tdm_dev'])
    actual = declarations + '\n' + '\n\n'.join(bodies.values()) + '\n'
    (output / 'actual-functions.c').write_text(actual)
    for name in ['pm-model-declarations.h', 'test-format-pm-main.c']:
        (output / name).write_bytes((HERE / name).read_bytes())
    unit = output / 'unit.c'
    unit.write_text(('#define EXPECT_RED 1\n' if args.red_v11 else '#define HAVE_FORMAT_PM_RELEASE 1\n') +
                    '#include "test-params-shim.h"\n#include "actual-abi.h"\n' + actual +
                    '\n#include "test-format-pm-main.c"\n')
    receipt = {'model_only': True, 'board_tested': False, 'expected_red': args.red_v11,
               'source_sha256': sha(source_path.read_bytes()),
               'production_functions_sha256': {name: sha(body.encode()) for name, body in bodies.items()},
               'runner_sha256': sha(Path(__file__).read_bytes()),
               'main_sha256': sha((HERE / 'test-format-pm-main.c').read_bytes()),
               'boundary': 'Byte-exact production functions. PM scheduling/CCF/regmap/IRQ/pinctrl are API models. Deterministic interleavings expose a possible race, not captured board scheduling. Failstop longjmp only observes the production teardown rejection; physical panic never returns.',
               'runs': {}}
    (output / 'runner-snapshot.py').write_bytes(Path(__file__).read_bytes())
    for label, compiler, flags, prefix in [
            ('host', 'gcc', [], []),
            ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'], []),
            ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-static'], [str(ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static')])]:
        binary = output / ('format-pm-' + label)
        argv = [compiler, '-std=gnu11', '-O0', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', '-Wno-unused-function', '-pthread', *flags, str(unit), '-o', str(binary)]
        compiled = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (output / (label + '-compile.stdout')).write_text(compiled.stdout)
        (output / (label + '-compile.stderr')).write_text(compiled.stderr)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)
        executed = subprocess.run(prefix + [str(binary)], capture_output=True, text=True, timeout=60)
        (output / (label + '.stdout')).write_text(executed.stdout)
        (output / (label + '.stderr')).write_text(executed.stderr)
        tests = json.loads(executed.stdout.splitlines()[-1])
        failures = [line.split(' ')[1] for line in executed.stdout.splitlines()
                    if line.startswith('FORMAT_PM_CHECK ') and line.endswith(' 0')]
        expected = ['worker_before_fmt_out_reaches_idle'] if args.red_v11 else []
        valid = failures == expected and executed.returncode == int(args.red_v11)
        receipt['runs'][label] = {'compile_argv': argv, 'execute_argv': prefix + [str(binary)],
                                  'exit': executed.returncode, 'tests': tests, 'failures': failures,
                                  'expected_red_reproduced': args.red_v11 and valid,
                                  'binary_sha256': sha(binary.read_bytes()),
                                  'stdout_sha256': sha(executed.stdout.encode()),
                                  'stderr_sha256': sha(executed.stderr.encode())}
        (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if not valid:
            raise RuntimeError(f'{label}: {failures}; {executed.stderr}')
    print(json.dumps({'expected_red': args.red_v11,
                      'runs': {name: item['tests'] for name, item in receipt['runs'].items()}}))


if __name__ == '__main__':
    main()
