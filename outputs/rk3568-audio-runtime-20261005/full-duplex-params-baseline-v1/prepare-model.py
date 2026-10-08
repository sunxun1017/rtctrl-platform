#!/usr/bin/env python3
"""Create a fresh old-production params caller model; never edit production or old model."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat

HERE = Path(__file__).resolve().parent
AUDIO = HERE.parent
ROOT = AUDIO.parents[1]
OLD = AUDIO / 'asoc-open-rollback-v1/model-green-v2'
DESIGN = AUDIO / 'full-duplex-configuration-design-v1'
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordinary(path):
    if not path.is_relative_to(ROOT) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Ordinary source required')
    ancestor = path.parent
    while True:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError('Nonordinary source ancestor')
        if ancestor == ROOT:
            break
        ancestor = ancestor.parent
    return path


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected one model patch: ' + old[:100])
    return text.replace(old, new)


def function(text, name):
    match = re.search(r'^[A-Za-z_][A-Za-z_0-9 \t*\n]*\b' + name + r'\([^;{}]*?\)\s*\{', text, re.M)
    if not match:
        raise ValueError('Missing real function: ' + name)
    depth = 0
    for index in range(text.index('{', match.start()), len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if depth == 0:
            return text[match.start():index + 1]
    raise ValueError('Unclosed function')


def main():
    if sha(ordinary(OLD / 'input-manifest.json')) != '4c043676fe48a47a983375ef392a45a930adcbc9ecdab3c68bd3511215b6630b':
        raise ValueError('Frozen old model identity changed')
    old_inventory = ordinary(OLD.parent / 'sealed-v1/file-manifest.json')
    if sha(old_inventory) != 'b22e81e766943c704e0a55c84785aad00cd18295189d417e815d804a8bae3f14':
        raise ValueError('Accepted old seal manifest changed')
    expected_old = {rel.split('/', 1)[1]: digest for rel, digest in json.loads(old_inventory.read_text())['files_sha256'].items() if rel.startswith('model-green-v2/')}
    actual_old = {p.name: sha(ordinary(p)) for p in OLD.iterdir()}
    if actual_old != expected_old:
        raise ValueError('Old model exact set/content changed')
    design_manifest = json.loads(ordinary(DESIGN / 'input-manifest.json').read_text())
    if sha(DESIGN / 'input-manifest.json') != 'd00a4bf2c174958ff9271f03f9928095922c4e818bc79d37139081f1b45b7167':
        raise ValueError('Source identity manifest changed')
    mirrors = {}
    for rel, entry in design_manifest['source_to_Image_inventory'].items():
        path = ordinary(ROOT / entry['actual_SOURCE'])
        actual = {'bytes': path.stat().st_size, 'mode': stat.S_IMODE(path.stat().st_mode), 'sha256': sha(path)}
        if actual != entry['ordinary'] or actual['sha256'] != entry['Image_inventory_entry']['sha256']:
            raise ValueError('Actual SOURCE finite mirror drift: ' + rel)
        mirrors[rel] = actual
    out = HERE / 'model-v1'
    out.mkdir(exist_ok=False)
    originals = {}
    for path in sorted(OLD.iterdir()):
        ordinary(path)
        shutil.copy2(path, out / path.name)
        originals[str(path.relative_to(ROOT))] = sha(path)
    (out / 'previous-input-manifest.json').write_bytes((out / 'input-manifest.json').read_bytes())
    contract = out / 'contract-evidence'
    contract.mkdir()
    for name in ['DESIGN.md', 'MODEL-PLAN.md', 'input-manifest-v3.json', 'design-readback-v3.json']:
        shutil.copy2(ordinary(DESIGN / name), contract / name)
    source_out = out / 'production-source-inputs'
    source_out.mkdir()
    sources = {}
    for rel, entry in design_manifest['inputs'].items():
        source = ordinary(ROOT / rel)
        if sha(source) != entry['sha256']:
            raise ValueError('Latest source drift')
        leaf = Path(entry['snapshot']).name
        shutil.copy2(source, source_out / leaf)
        sources[leaf] = source.read_text()
    extra = []
    added = {}
    groups = {
        'rk817_codec.c': ['rk817_restart_dac_digital_clk_and_apll', 'rk817_restart_adc_digital_clk_and_apll', 'rk817_hw_params', 'rk817_codec_shutdown'],
        'soc-link.c': ['snd_soc_link_be_hw_params_fixup', 'snd_soc_link_hw_params', 'snd_soc_link_hw_free'],
        'soc-dai.c': ['snd_soc_dai_hw_params', 'snd_soc_dai_hw_free', 'snd_soc_dai_digital_mute'],
        'soc-component.c': ['snd_soc_pcm_component_hw_params', 'snd_soc_pcm_component_hw_free'],
        'soc-generic-dmaengine-pcm.c': ['snd_dmaengine_pcm_prepare_slave_config', 'dmaengine_pcm_hw_params'],
        'soc-dai.h': ['snd_soc_dai_stream_active'],
        'soc-pcm.c': ['soc_pcm_has_mute', 'soc_pcm_params_symmetry', 'soc_pcm_codec_params_fixup', 'soc_pcm_hw_params', 'soc_pcm_hw_free'],
    }
    for leaf, names in groups.items():
        for name in names:
            body = function(sources[leaf], name)
            extra.append(body)
            added[leaf + ':' + name] = hashlib.sha256(body.encode()).hexdigest()
    (out / 'actual-params-functions.c').write_text('\n\n'.join(extra) + '\n')
    for name in ['params-events.h', 'params-api.h', 'test-params-caller.c']:
        shutil.copy2(ordinary(HERE / name), out / name)
    shutil.copy2(source_out / 'rk817_codec.h', out / 'rk817_codec.h')
    glue = (out / 'model-glue.h').read_text()
    glue = replace(glue, '    const struct snd_soc_compress_ops *compress_ops;\n',
        '    const struct snd_soc_compress_ops *compress_ops;\n    int (*hw_params)(struct snd_soc_component *, struct snd_pcm_substream *, struct snd_pcm_hw_params *);\n    int (*hw_free)(struct snd_soc_component *, struct snd_pcm_substream *);\n')
    glue = replace(glue, '    int (*trigger)(struct snd_pcm_substream *, int, struct snd_soc_dai *);\n',
        '    int (*trigger)(struct snd_pcm_substream *, int, struct snd_soc_dai *);\n    int (*hw_params)(struct snd_pcm_substream *, struct snd_pcm_hw_params *, struct snd_soc_dai *);\n    void (*hw_free)(struct snd_pcm_substream *, struct snd_soc_dai *);\n    int (*mute_stream)(struct snd_soc_dai *, int, int);\n    bool no_capture_mute;\n')
    glue = replace(glue, '    int (*trigger)(struct snd_pcm_substream *, int);\n',
        '    int (*trigger)(struct snd_pcm_substream *, int);\n    int (*hw_params)(struct snd_pcm_substream *, struct snd_pcm_hw_params *);\n    void (*hw_free)(struct snd_pcm_substream *);\n')
    glue = replace(glue, 'bool dynamic, no_pcm, symmetric_rates, symmetric_channels, symmetric_samplebits; };',
        'bool dynamic, no_pcm, symmetric_rates, symmetric_channels, symmetric_samplebits; int (*be_hw_params_fixup)(struct snd_soc_pcm_runtime *, struct snd_pcm_hw_params *); };')
    glue = replace(glue, 'struct rk817_codec_priv { unsigned int stereo_sysclk; };',
        'struct rk817_codec_priv { unsigned int stereo_sysclk, chip_ver; bool pdmdata_out_enable; };')
    glue = 'struct snd_soc_pcm_runtime;\n' + glue
    glue = replace(glue, 'static int snd_soc_dai_digital_mute(struct snd_soc_dai *dai, int mute, int stream)\n{ (void)dai; (void)mute; (void)stream; return 0; }',
        'int snd_soc_dai_digital_mute(struct snd_soc_dai *dai, int mute, int stream);')
    (out / 'model-glue.h').write_text(glue)
    macros = (out / 'actual-iteration-mark-macros.h').read_text()
    soc_header = sources['soc.h']
    for name in ['for_each_rtd_cpu_dais', 'for_each_rtd_cpu_dais_rollback', 'for_each_rtd_codec_dais', 'for_each_rtd_codec_dais_rollback']:
        match = re.search(r'^#define ' + name + r'\([^\n]*\n(?:[^\n]*\\\n)*[^\n]*', soc_header, re.M)
        if not match:
            raise ValueError('Missing real iteration macro')
        macros += '\n' + match.group(0) + '\n'
    (out / 'actual-iteration-mark-macros.h').write_text(macros)
    shim = (out / 'test-params-shim.h').read_text()
    shim = replace(shim, '    int ret = fault_operation();\n    clock_calls++;\n    if (!ret) clk->rate = rate;',
        '    int ret = fault_operation();\n    if (params_phase == 3 && params_inject_cpu_clock) { ret = -EREMOTEIO; params_inject_cpu_clock = false; }\n    params_note("CCF_SET_RATE", (unsigned int)rate, ret);\n    clock_calls++;\n    if (!ret) clk->rate = rate;')
    shim = replace(shim, 'static unsigned long clk_get_rate(struct clk *clk) { return clk->rate; }',
        'static unsigned long clk_get_rate(struct clk *clk) { params_note("CCF_GET_RATE_API", (unsigned int)clk->rate, 0); return clk->rate; }')
    (out / 'test-params-shim.h').write_text(shim)
    fixture = (out / 'test-caller-chain.c').read_text()
    hook = '''    if (function == (void *)asoc_simple_hw_params) { params_phase = 1; params_note("MACHINE_BEGIN", 0, 0); }
    if (function == (void *)rk817_hw_params) { params_phase = 2; params_note("CODEC_BEGIN", 0, 0); }
    if (function == (void *)i2s_checked_hw_params) { params_phase = 3; params_note("CPU_BEGIN", 0, 0); }
    if (function == (void *)snd_soc_pcm_component_hw_params) { params_phase = 4; params_note("COMPONENT_BEGIN", 0, 0); }
    if (function == (void *)dmaengine_pcm_hw_params) params_note("DMA_BEGIN", 0, 0);
    if (function == (void *)rk817_set_dai_sysclk) params_note("CODEC_SYSCLK_CACHE_CALLBACK", 0, 0);
    if (function == (void *)rockchip_i2s_tdm_set_sysclk) params_note("CPU_SYSCLK_CALLBACK", 0, 0);
    if (function == (void *)soc_pcm_trigger) params_note("PCM_TRIGGER_BEGIN", 0, 0);
    if (function == (void *)snd_soc_pcm_component_trigger) params_note("COMPONENT_TRIGGER_BEGIN", 0, 0);
    if (function == (void *)snd_soc_pcm_dai_trigger) params_note("DAI_TRIGGER_BEGIN", 0, 0);
    if (function == (void *)i2s_checked_component_trigger) params_note("CPU_COMPONENT_TRIGGER_GATE", 0, 0);
    if (function == (void *)i2s_checked_trigger) {
        params_note("CPU_DAI_TRIGGER_BEGIN", 0, 0);
        if (params_inject_start_error) { fault_at = operations + 1; params_inject_start_error = false; params_note("INJECT_CPU_TRIGGER_API_ERROR", 0, -EREMOTEIO); }
    }
'''
    fixture = replace(fixture, '    (void)caller;\n', '    (void)caller;\n' + hook)
    fixture = replace(fixture, '{ (void)function; (void)caller; }', '''{
    (void)caller;
    if (function == (void *)asoc_simple_hw_params) params_note("MACHINE_END", 0, 0);
    if (function == (void *)rk817_hw_params) params_note("CODEC_END", 0, 0);
    if (function == (void *)i2s_checked_hw_params) params_note("CPU_END", 0, 0);
    if (function == (void *)snd_soc_pcm_component_hw_params) params_note("COMPONENT_END", 0, 0);
    if (function == (void *)dmaengine_pcm_hw_params) params_note("DMA_END", 0, 0);
    if (function == (void *)soc_pcm_trigger) params_note("PCM_TRIGGER_END", 0, 0);
    if (function == (void *)snd_soc_pcm_component_trigger) params_note("COMPONENT_TRIGGER_END", 0, 0);
    if (function == (void *)snd_soc_pcm_dai_trigger) params_note("DAI_TRIGGER_END", 0, 0);
}''')
    fixture = replace(fixture, '    .set_sysclk = rockchip_i2s_tdm_set_sysclk,\n',
        '    .set_sysclk = rockchip_i2s_tdm_set_sysclk,\n    .hw_params = rockchip_i2s_tdm_hw_params,\n')
    fixture = replace(fixture, 'codec_ops = {.set_sysclk = rk817_set_dai_sysclk,',
        'codec_ops = {.hw_params = rk817_hw_params, .set_sysclk = rk817_set_dai_sysclk,')
    fixture = replace(fixture, '.trigger = codec_trigger, .startup = codec_startup', '.mute_stream = params_codec_mute_api, .shutdown = rk817_codec_shutdown')
    fixture = replace(fixture, '    (void)component;\n    if (cmd == SNDRV_PCM_TRIGGER_START',
        '    (void)component;\n    params_note("DMA_TRIGGER_API", ss->stream, cmd);\n    if (cmd == SNDRV_PCM_TRIGGER_START')
    fixture = replace(fixture, 'platform_component_ops = {.trigger = platform_trigger,',
        'platform_component_ops = {.hw_params = dmaengine_pcm_hw_params, .trigger = platform_trigger,')
    fixture = replace(fixture, 'link_ops = {.startup = asoc_simple_startup,',
        'link_ops = {.hw_params = asoc_simple_hw_params, .startup = asoc_simple_startup,')
    (out / 'test-caller-chain.c').write_text(fixture)
    unit = (out / 'unit.c').read_text()
    unit = '#include "params-events.h"\n' + unit
    unit = replace(unit, '#include "model-glue.h"\n', '#include "model-glue.h"\n#include "params-api.h"\n')
    unit = replace(unit, '#include "test-caller-chain.c"',
        '#include "actual-params-functions.c"\n#define main old_harness_main_not_executed\n#include "test-caller-chain.c"\n#undef main\n#include "test-params-caller.c"')
    (out / 'unit.c').write_text(unit)
    old_manifest = json.loads((out / 'previous-input-manifest.json').read_text())
    record = {'status': 'PREPARED_FOR_PARENT_SOURCE_REVIEW_NOT_EXECUTED',
        'old_model_inputs_sha256': originals, 'source_identity_manifest_sha256': sha(DESIGN / 'input-manifest.json'),
        'old_seal_manifest_sha256': sha(old_inventory),
        'contract_evidence_sha256': {p.name: sha(p) for p in sorted(contract.iterdir())},
        'actual_SOURCE_finite_mirrors': mirrors,
        'source_inputs': {p.name: sha(p) for p in sorted(source_out.iterdir())},
        'inherited_production_functions_sha256': old_manifest['production_functions_sha256'],
        'added_production_functions_sha256': added,
        'model_files_sha256': {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'input-manifest.json'},
        'expected_business_red_count': 8, 'expected_observation_count': 76,
        'model_executed': False, 'production_modified': False, 'Kbuild_executed': False, 'board_tested': False,
        'CPU_START_gate_modified': False, 'preparation_tool_sha256': sha(Path(__file__))}
    (out / 'input-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'added_real_functions': len(added), 'inherited_real_functions': len(old_manifest['production_functions_sha256']),
        'model_manifest_sha256': sha(out / 'input-manifest.json'), 'model_executed': False}))


if __name__ == '__main__':
    main()
