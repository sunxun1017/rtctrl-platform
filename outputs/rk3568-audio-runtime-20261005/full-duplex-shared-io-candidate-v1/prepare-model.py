#!/usr/bin/env python3
"""Extract finite real bodies; no compiler or model is executed here."""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARAMS = HERE.parent / 'full-duplex-params-candidate-v1'
spec = importlib.util.spec_from_file_location('source_utils', PARAMS / 'model-v4/source_utils.py')
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)
function, declaration, sha = utils.function, utils.declaration, utils.sha

CODEC = 'sound/soc/codecs/rk817_codec.c'
CPU = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
CARD = 'sound/soc/soc-core.c'
HEADER = 'include/sound/soc-dai.h'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--terminal', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch('model-[a-z0-9-]+', args.model):
        raise ValueError('Fresh local model directory required')
    if args.source != 'inputs-v1' and not re.fullmatch('source-v[1-9][0-9]*', args.source):
        raise ValueError('Versioned finite source required')
    source = HERE / args.source
    output = HERE / args.model
    output.mkdir()
    texts = {rel: (source / rel).read_text() for rel in [CODEC, CPU, CARD, HEADER]}
    bodies = {}
    names = ['rk817_codec_ctl_gpio', 'rk817_restart_dac_digital_clk',
             'rk817_restart_adc_digital_clk', 'rk817_codec_power_up',
             'rk817_codec_power_down', 'rk817_playback_path_config',
             'rk817_capture_path_config', 'rk817_playback_path_get',
             'rk817_playback_path_put', 'rk817_capture_path_get',
             'rk817_capture_path_put', 'rk817_resume_path_get',
             'rk817_resume_path_put', 'rk817_set_dai_fmt',
             'rk817_digital_mute_dac', 'rk817_digital_mute_adc',
             'rk817_digital_mute', 'rk817_codec_shutdown',
             'rk817_shared_startup', 'rk817_shared_free', 'rk817_shared_fault',
             'rk817_shared_set_fmt', 'rk817_shared_shutdown']
    names += re.findall(r'^static int (rk817_shared_(?:power_up|power_down|playback_apply|capture_apply|path_config|mute|capture_shutdown))\(', texts[CODEC], re.M)
    if args.terminal:
        names += ['rk817_reset', 'rk817_probe', 'rk817_remove', 'rk817_platform_remove',
                  'rk817_platform_shutdown', 'rk817_suspend', 'rk817_resume', 'rk817_shared_sysclk']
        names += re.findall(r'^static (?:void|int) (rk817_shared_(?:failstop|quiesce|probe|terminal_check))\(', texts[CODEC], re.M)
    # Preserve source order, important for helper definitions used by controls.
    codec_bodies = sorted([(texts[CODEC].index(function(texts[CODEC], name)), name,
                           function(texts[CODEC], name)) for name in names])
    for _, name, body in codec_bodies:
        bodies[CODEC + ':' + name] = sha(body.encode())
    macro = re.search(r'^#define RK817_SHARED_TRY\(call\)[\s\S]*?^\} while \(0\)', texts[CODEC], re.M)
    functions = '\n\n'.join(body for _, _, body in codec_bodies)
    if macro:
        functions = macro[0] + '\n\n' + functions + '\n#undef RK817_SHARED_TRY\n'
    (output / 'actual-codec-functions.c').write_text(functions + '\n')
    arrays = texts[CODEC][texts[CODEC].index('static struct rk817_reg_val_typ playback_power_up_list'):texts[CODEC].index('static int rk817_codec_power_up')]
    (output / 'actual-power-arrays.h').write_text(arrays)
    (output / 'actual-codec-type.h').write_text(declaration(texts[CODEC], 'struct', 'rk817_codec_priv') + '\n')
    (output / 'actual-state.h').write_text(declaration(texts[HEADER], 'struct', 'snd_soc_dai_params_state') + '\n')
    header_functions = [function(texts[HEADER], n) for n in ['snd_soc_dai_params_free_locked', 'snd_soc_dai_hw_params_any']]
    for name, body in zip(['snd_soc_dai_params_free_locked', 'snd_soc_dai_hw_params_any'], header_functions):
        bodies[HEADER + ':' + name] = sha(body.encode())
    (output / 'actual-header-functions.h').write_text('\n\n'.join(header_functions) + '\n')
    pm_names = ['snd_soc_suspend', 'snd_soc_poweroff']
    if 'snd_soc_card_shared_params_any' in texts[CARD]:
        pm_names.insert(0, 'snd_soc_card_shared_params_any')
    pm_functions = [function(texts[CARD], name) for name in pm_names]
    for name, body in zip(pm_names, pm_functions):
        bodies[CARD + ':' + name] = sha(body.encode())
    (output / 'actual-card-functions.c').write_text('\n\n'.join(pm_functions) + '\n')
    external_sources = {}
    if args.terminal:
        core_names = ['soc_remove_component', 'soc_cleanup_card_resources', 'snd_soc_unbind_card']
        if 'int snd_soc_component_shutdown_card(' in texts[CARD]:
            core_names += ['snd_soc_component_shutdown_card']
        core_bodies = [function(texts[CARD], name) for name in core_names]
        for name, body in zip(core_names, core_bodies):
            bodies[CARD + ':' + name] = sha(body.encode())
        sdk_init = HERE.parents[2] / '.deps/kernel-source/aiot-3568pq-audio-v4/sound/core/init.c'
        external_sources['@sdk/sound/core/init.c'] = sha(sdk_init.read_bytes())
        sync_body = function(sdk_init.read_text(), 'snd_card_disconnect_sync')
        bodies['@sdk/sound/core/init.c:snd_card_disconnect_sync'] = sha(sync_body.encode())
        core_unit = sync_body + '\n\n' + '\n\n'.join(core_bodies) + '\n'
        if len(core_names) == 3:
            core_unit += '''
static int snd_soc_component_shutdown_card(struct device *dev,
        const struct snd_soc_component_driver *driver, unsigned int timeout_ms)
{ (void)dev; (void)driver; (void)timeout_ms; return -EOPNOTSUPP; }
'''
        (output / 'actual-terminal-core.c').write_text(core_unit)
    # Preserve actual predicate placement relative to CONFIG_PM_SLEEP, while the
    # omitted resume/late sections are replaced with this explicit closing guard.
    pm_guard = texts[CARD].index('#ifdef CONFIG_PM_SLEEP\n')
    pm_start = pm_guard
    if 'snd_soc_card_shared_params_any' in texts[CARD]:
        pm_start = min(pm_start, texts[CARD].index(function(texts[CARD], 'snd_soc_card_shared_params_any')))
    suspend_body = function(texts[CARD], 'snd_soc_suspend')
    prefix = texts[CARD][pm_start:texts[CARD].index(suspend_body) + len(suspend_body)]
    no_pm = ('#include "model-api.h"\n#include "actual-header-functions.h"\n' + prefix + '\n#endif\n' +
             function(texts[CARD], 'snd_soc_poweroff') + '''
int main(void)
{
    (void)dai; (void)component; (void)clock_model; (void)streams; (void)control;
    struct snd_soc_dai_ops ops = {.hw_params_fault = &ops};
    struct snd_soc_dai_driver driver = {.ops = &ops};
    struct snd_soc_dai dai = {.driver = &driver};
    struct snd_soc_pcm_runtime rtd = {.num_cpus = 1, .dais = {&dai}};
    struct snd_soc_card card = {.instantiated = true, .count = 1, .rtds = {&rtd}};
    struct device device = {.data = &card};
    int ret = snd_soc_poweroff(&device);
    printf("CARD_NO_PM_SLEEP %d %u\\n", ret, pm_side_effects);
    return ret == -EOPNOTSUPP && !pm_side_effects ? 0 : 1;
}
''')
    (output / 'unit-no-pm-sleep.c').write_text(no_pm)
    body = function(texts[CPU], 'i2s_checked_runtime_suspend')
    bodies[CPU + ':i2s_checked_runtime_suspend'] = sha(body.encode())
    (output / 'actual-cpu-function.c').write_text(body + '\n')
    match = re.search(r'^static const struct snd_soc_dai_ops rk817_shared_dai_ops = \{[\s\S]*?^\};', texts[CODEC], re.M)
    registration = match[0]
    (output / 'actual-codec-registration.c').write_text(registration + '\n')
    selected = []
    for field in ['mute_stream', 'shutdown']:
        name = re.search(r'\.' + field + r'\s*=\s*(\w+)', registration)[1]
        selected.append('#define MODEL_' + field.upper() + ' ' + name)
    selected.append('#define MODEL_RETAINED(stream) ' + ('codec.retained_clock[(stream)]' if 'bool retained_clock[2];' in texts[CODEC] else 'false'))
    if args.terminal:
        present = 'bool terminal_started;' in texts[CODEC]
        for field in ['terminal_started', 'terminal_done', 'probe_clock_owned', 'clk_lock_initialized']:
            selected.append('#define MODEL_' + field.upper() + ' ' + ('codec.' + field if present else 'false'))
        selected.append('#define MODEL_SHUTDOWN_STARTED ' + ('codec.shutdown_started' if 'bool shutdown_started;' in texts[CODEC] else 'false'))
    (output / 'selected-callbacks.h').write_text('\n'.join(selected) + '\n')
    header = PARAMS / 'model-v4/rk817_codec.h'
    (output / 'rk817_codec.h').write_bytes(header.read_bytes())
    for name in ['model-api.h', 'test-shared-io.c']:
        (output / name).write_bytes((HERE / name).read_bytes())
    lines = [
        '#include "terminal-api.h"' if args.terminal else '#include "model-api.h"', '#include "actual-header-functions.h"',
        '#include "actual-power-arrays.h"', '#include "actual-codec-functions.c"',
        '#include "selected-callbacks.h"', '#include "actual-card-functions.c"',
        '#include "actual-cpu-function.c"']
    if args.terminal:
        for name in ['terminal-api.h', 'terminal-glue.c', 'test-terminal.c']:
            (output / name).write_bytes((HERE / name).read_bytes())
        lines += ['#include "terminal-glue.c"', '#include "actual-terminal-core.c"', '#define main peripheral_main',
                  '#include "test-shared-io.c"', '#undef main', '#include "test-terminal.c"', '']
    else:
        lines += ['#include "test-shared-io.c"', '']
    (output / 'unit.c').write_text('\n'.join(lines))
    records = {p.name: sha(p.read_bytes()) for p in output.iterdir() if p.is_file()}
    (output / 'manifest.json').write_text(json.dumps({
        'scope': 'FINITE_PRIMITIVE_MODEL_NO_KERNEL_LAYOUT_OR_HARDWARE_PROOF',
        'source': args.source,
        'source_files': {rel: sha((source / rel).read_bytes()) for rel in texts},
        'external_source_files': external_sources,
        'actual_bodies_sha256': bodies,
        'model_files_sha256': records,
        'registration_sha256': sha(registration.encode()),
        'compiler_executed': False,
    }, indent=2) + '\n')
    print(json.dumps({'prepared_model': args.model, 'actual_functions': len(bodies), 'compiler_executed': False}))


if __name__ == '__main__':
    main()
