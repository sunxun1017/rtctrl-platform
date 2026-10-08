#!/usr/bin/env python3
"""Build only the private three-source delta; keep legacy functions byte-identical."""
import argparse
import difflib
import importlib.util
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARAMS = HERE.parent / 'full-duplex-params-candidate-v1'
spec = importlib.util.spec_from_file_location('source_utils', PARAMS / 'model-v4/source_utils.py')
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)
function, replace, sha = utils.function, utils.replace, utils.sha
CODEC = 'sound/soc/codecs/rk817_codec.c'
CPU = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
CARD = 'sound/soc/soc-core.c'

TRY = '''/* Used only by the checked helpers below; every operation preserves errno. */
#define RK817_SHARED_TRY(call) do { \\
\tret = (call); \\
\tif (ret < 0) \\
\t\treturn ret; \\
} while (0)
'''


def checked_io(body):
    pattern = r'(?m)^([ \t]*)(snd_soc_component_(?:write|update_bits)|rk817_codec_power_(?:up|down)|rk817_restart_(?:dac|adc)_digital_clk)\(([\s\S]*?)\);'

    def check(match):
        name = match[2].replace('rk817_codec_power_', 'rk817_shared_power_')
        return match[1] + 'RK817_SHARED_TRY(' + name + '(' + match[3] + '));'

    return re.sub(pattern, check, body)


def helpers(source):
    parts = [TRY]
    for kind in ['up', 'down']:
        name = 'rk817_codec_power_' + kind
        body = function(source, name)
        body = body.replace(name, 'rk817_shared_power_' + kind, 1)
        body = replace(body, '\tint i;', '\tint i, ret;')
        parts.append(checked_io(body))
    for direction in ['playback', 'capture']:
        old = function(source, 'rk817_' + direction + '_path_config')
        switch = old[old.index('\tswitch ('):]
        switch = switch.replace('switch (rk817->' + direction + '_path)', 'switch (target_path)', 1)
        body = ('static int rk817_shared_' + direction + '_apply(struct snd_soc_component *component,\n'
                '\t\t\t\t\tlong pre_path, long target_path)\n{\n'
                '\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);\n'
                '\tint ret;\n\n' + switch)
        parts.append(checked_io(body))
    parts.append('#undef RK817_SHARED_TRY')
    parts.append('''/* Caller owns params_lock; successful path state is published after all I/O. */
static int rk817_shared_path_config(struct snd_soc_component *component,
\t\t\t\t   int stream, long target_path)
{
\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);
\tstruct snd_soc_dai_params_state *p = &rk817->shared_params;
\tlong *path = stream ? &rk817->capture_path : &rk817->playback_path;
\tunsigned int *lease = stream ? &rk817->clk_capture : &rk817->clk_playback;
\tbool new_clock = false;
\tint ret;

\tif (target_path < 0 || target_path > (stream ? BT_SCO_MIC : RING_SPK_HP))
\t\treturn -EINVAL;
\t/* A same-value observation is not a recovery or an I/O operation. */
\tif (*path == target_path)
\t\treturn 0;
\tif (p->pending || p->owner[0] || p->owner[1])
\t\treturn -EBUSY;
\tif (rk817->params_error)
\t\treturn rk817->params_error;

\tif (target_path && !*lease) {
\t\tmutex_lock(&rk817->clk_lock);
\t\tret = clk_prepare_enable(rk817->mclk);
\t\tmutex_unlock(&rk817->clk_lock);
\t\tif (ret < 0)
\t\t\treturn ret;
\t\tnew_clock = true;
\t}
\tif (stream)
\t\tret = rk817_shared_capture_apply(component, *path, target_path);
\telse
\t\tret = rk817_shared_playback_apply(component, *path, target_path);
\tif (ret < 0) {
\t\t/* A partial codec write does not establish a reversible physical state. */
\t\tif (new_clock)
\t\t\trk817->retained_clock[stream] = true;
\t\tif (!rk817->params_error)
\t\t\trk817->params_error = ret;
\t\treturn ret;
\t}

\tmutex_lock(&rk817->clk_lock);
\tif (!target_path && *lease)
\t\tclk_disable_unprepare(rk817->mclk);
\t*lease = target_path ? 1 : 0;
\t*path = target_path;
\tmutex_unlock(&rk817->clk_lock);
\treturn 0;
}''')
    return '\n\n'.join(parts) + '\n\n'


def codec_candidate(source):
    output = replace(source, '\tint params_error;', '''\tint params_error;
\t/* Actual MCLK references retained after an uncertain checked path write. */
\tbool retained_clock[2];''')
    insert = helpers(source)
    output = replace(output, 'static int rk817_playback_path_get(', insert + 'static int rk817_playback_path_get(')
    for kind in ['playback', 'capture', 'resume']:
        name = 'rk817_' + kind + '_path_put'
        old = function(output, name)
        marker = '\n\tif (rk817->' if kind != 'resume' else '\n\trk817->resume_path ='
        pos = old.index(marker)
        stream = 0 if kind == 'playback' else 1
        branch = '''
\tif (rk817->shared_params_enabled) {
\t\tlong value = ucontrol->value.integer.value[0];
\t\tint ret;

\t\tmutex_lock(&rk817->params_lock);
'''
        if kind != 'resume':
            branch += '\t\tret = rk817_shared_path_config(component, ' + str(stream) + ', value);\n'
        else:
            branch += '''\t\tif (value < 0 || value > 1)
\t\t\tret = -EINVAL;
\t\telse if (rk817->resume_path == value)
\t\t\tret = 0;
\t\telse if (rk817->shared_params.pending || rk817->shared_params.owner[0] ||
\t\t\t rk817->shared_params.owner[1])
\t\t\tret = -EBUSY;
\t\telse if (rk817->params_error)
\t\t\tret = rk817->params_error;
\t\telse {
\t\t\trk817->resume_path = value;
\t\t\tret = 0;
\t\t}
'''
        branch += '''\t\tmutex_unlock(&rk817->params_lock);
\t\treturn ret;
\t}
'''
        output = replace(output, old, old[:pos] + branch + old[pos:])
        name = 'rk817_' + kind + '_path_get'
        old = function(output, name)
        prefix = '\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);'
        new = replace(old, prefix, prefix + '''

\tif (rk817->shared_params_enabled)
\t\tmutex_lock(&rk817->params_lock);
''')
        new = replace(new, '\treturn 0;', '''\tif (rk817->shared_params_enabled)
\t\tmutex_unlock(&rk817->params_lock);

\treturn 0;''')
        output = replace(output, old, new)
    old = function(output, 'rk817_shared_set_fmt')
    new = replace(old, '''\tif (!ret && (p->pending || p->owner[0] || p->owner[1]))
\t\tret = rk817->shared_dai_fmt == fmt ? 0 : -EBUSY;''', '''\tif (!ret && rk817->shared_dai_fmt == fmt)
\t\tret = 0;
\telse if (!ret && (p->pending || p->owner[0] || p->owner[1]))
\t\tret = -EBUSY;''')
    output = replace(output, old, new)
    old = function(output, 'rk817_shared_shutdown')
    new = '''/* mute_stream has no substream argument; use the independently held open slot. */
static int rk817_shared_mute(struct snd_soc_dai *dai, int mute, int stream)
{
\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
\tstruct snd_soc_dai_params_state *p = &rk817->shared_params;
\tint ret;

\tif (dai->id != RK817_HIFI || (stream != 0 && stream != 1))
\t\treturn -EINVAL;
\tmutex_lock(&rk817->params_lock);
\tif (!rk817->shared_open[stream])
\t\tret = -EINVAL;
\telse if (p->pending)
\t\tret = -EBUSY;
\telse if (!mute && (rk817->params_error || rk817->mute_io_error))
\t\tret = rk817->params_error ? rk817->params_error : rk817->mute_io_error;
\telse if (!mute && p->owner[stream] != rk817->shared_open[stream])
\t\tret = -EINVAL;
\telse {
\t\t/* Post-HW_FREE mute still owns the open, even after its params owner left. */
\t\tret = rk817_digital_mute(dai, mute, stream);
\t\tif (ret < 0 && !rk817->params_error)
\t\t\trk817->params_error = ret;
\t}
\tmutex_unlock(&rk817->params_lock);
\treturn ret;
}

static int rk817_shared_capture_shutdown(struct snd_soc_component *component)
{
\tint first, ret;

\tfirst = snd_soc_component_update_bits(component, RK817_CODEC_DTOP_DIGEN_CLKE,
\t\t\t\t\t      I2STX_CKE_EN, I2STX_CKE_EN);
\tusleep_range(1000, 1100);
\t/* Try to clear this direction's bit even if the first update failed. */
\tret = snd_soc_component_update_bits(component, RK817_CODEC_DTOP_DIGEN_CLKE,
\t\t\t\t\t    I2STX_CKE_EN, I2STX_CKE_DIS);
\treturn first < 0 ? first : (ret < 0 ? ret : 0);
}

static void rk817_shared_shutdown(struct snd_pcm_substream *ss, struct snd_soc_dai *dai)
{
\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(dai->component);
\tint ret;

\tif (dai->id != RK817_HIFI || (ss->stream != 0 && ss->stream != 1))
\t\treturn;
\tmutex_lock(&rk817->params_lock);
\tif (rk817->shared_open[ss->stream] != ss)
\t\tgoto out; /* Failed startup or a repeated close owns no open slot. */
\tret = snd_soc_dai_params_free_locked(&rk817->shared_params, dai, ss);
\tif (ret < 0) {
\t\tif (!rk817->params_error)
\t\t\trk817->params_error = ret;
\t\tgoto out;
\t}
\tif (ss->stream == SNDRV_PCM_STREAM_CAPTURE) {
\t\t/* Masked ADC output pulse does not alter a peer's DAC/PLL/rate bits. */
\t\tret = rk817_shared_capture_shutdown(dai->component);
\t\tif (ret < 0 && !rk817->params_error)
\t\t\trk817->params_error = ret;
\t}
\trk817->shared_open[ss->stream] = NULL;
out:
\t/* This void callback records first errno but cannot return it to close(). */
\tmutex_unlock(&rk817->params_lock);
}'''
    output = replace(output, old, new)
    start = output.index('static const struct snd_soc_dai_ops rk817_shared_dai_ops')
    before = output[:start]
    after = output[start:]
    after = replace(after, '\t.mute_stream = rk817_digital_mute,', '\t.mute_stream = rk817_shared_mute,')
    return before + after


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if not re.fullmatch('v[2-9][0-9]*', args.version):
        raise ValueError('Fresh version required')
    out = HERE / ('source-' + args.version)
    shutil.copytree(HERE / 'inputs-v1', out, ignore=shutil.ignore_patterns('manifest.json'))
    originals = {rel: (HERE / 'inputs-v1' / rel).read_text() for rel in [CODEC, CPU, CARD]}
    outputs = {CODEC: codec_candidate(originals[CODEC])}
    cpu = originals[CPU]
    old = function(cpu, 'i2s_checked_runtime_suspend')
    new = replace(old, '''\tif (i2s_tdm->runtime_error && !i2s_tdm->shutting_down)''', '''\tif (i2s_tdm->shared_params_enabled &&
\t    (i2s_tdm->shared_params.pending || i2s_tdm->shared_params.owner[0] ||
\t     i2s_tdm->shared_params.owner[1]))
\t\tret = -EBUSY;
\telse if (i2s_tdm->runtime_error && !i2s_tdm->shutting_down)''')
    outputs[CPU] = replace(cpu, old, new)
    card = originals[CARD]
    predicate = '''/* Finite checked profile has no system low-power contract, including partial ops. */
static bool snd_soc_card_shared_params_any(struct snd_soc_card *card)
{
\tstruct snd_soc_pcm_runtime *rtd;
\tstruct snd_soc_dai *dai;
\tint i;

\tfor_each_card_rtds(card, rtd) {
\t\tfor_each_rtd_dais(rtd, i, dai) {
\t\t\tif (snd_soc_dai_hw_params_any(dai))
\t\t\t\treturn true;
\t\t}
\t}
\treturn false;
}

'''
    # poweroff is compiled outside CONFIG_PM_SLEEP, so its pure predicate must be too.
    card = replace(card, '#ifdef CONFIG_PM_SLEEP\n/* powers down audio subsystem for suspend */', predicate + '#ifdef CONFIG_PM_SLEEP\n/* powers down audio subsystem for suspend */')
    for name in ['snd_soc_suspend', 'snd_soc_poweroff']:
        old = function(card, name)
        new = replace(old, '''\tif (!card->instantiated)
\t\treturn 0;''', '''\tif (!card->instantiated)
\t\treturn 0;
\t/* Reject before wait/D3hot/mute, or before poweroff flush/DAPM side effects. */
\tif (snd_soc_card_shared_params_any(card))
\t\treturn -EOPNOTSUPP;''')
        card = replace(card, old, new)
    outputs[CARD] = card
    patches = []
    manifest = {}
    for rel, output in outputs.items():
        target = out / rel
        if target.read_text() != originals[rel]:
            raise ValueError('Private baseline already mutated ' + rel)
        target.write_text(output)
        patches.append(''.join(difflib.unified_diff(originals[rel].splitlines(True), output.splitlines(True),
                                                   fromfile='a/' + rel, tofile='b/' + rel)))
        manifest[rel] = {'baseline_sha256': sha(originals[rel].encode()),
                         'candidate_sha256': sha(output.encode()), 'bytes': len(output.encode())}
    patch = ''.join(patches)
    (HERE / ('shared-io-private-' + args.version + '.patch')).write_text(patch)
    for rel in ['include/sound/soc-dai.h', 'sound/soc/soc-pcm.c', 'sound/soc/generic/simple-card-utils.c']:
        data = (out / rel).read_bytes()
        if data != (HERE / 'inputs-v1' / rel).read_bytes():
            raise ValueError('Unexpected unrelated source delta')
    (HERE / ('source-manifest-' + args.version + '.json')).write_text(json.dumps({
        'scope': 'PRIVATE_THREE_SOURCE_DELTA_NO_KBUILD_NO_BOARD',
        'baseline_manifest_sha256': sha((HERE / 'inputs-v1/manifest.json').read_bytes()),
        'generator_sha256': sha(Path(__file__).read_bytes()),
        'files': manifest, 'patch_sha256': sha(patch.encode()),
    }, indent=2) + '\n')
    print(json.dumps({'changed_sources': len(outputs), 'patch_bytes': len(patch), 'compiler_executed': False}))


if __name__ == '__main__':
    main()
