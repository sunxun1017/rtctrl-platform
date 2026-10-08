#!/usr/bin/env python3
"""Private terminal increment over stable shared-I/O source-v3."""
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

HELPERS = '''/* A void teardown callback cannot stop devres release by returning errno. */
static void rk817_shared_failstop(const char *operation, int first_errno)
{
\tWRITE_ONCE(panic_timeout, 0);
\tpanic("rk817-codec: %s unsafe codec destruction (%d)", operation, first_errno);
}

/* params_lock drains all checked borrowers before terminal I/O or clock release. */
static void rk817_shared_quiesce(struct rk817_codec_priv *rk817, const char *operation)
{
\tstruct snd_soc_dai_params_state *p = &rk817->shared_params;
\tint ret = 0;

\tmutex_lock(&rk817->params_lock);
\trk817->terminal_started = true;
\tif (rk817->terminal_done)
\t\tgoto out;
\tif (rk817->params_error)
\t\tret = rk817->params_error;
\telse if (rk817->mute_io_error)
\t\tret = rk817->mute_io_error;
\telse if (p->pending || p->owner[0] || p->owner[1] ||
\t\t rk817->shared_open[0] || rk817->shared_open[1])
\t\tret = -EBUSY;
\telse if (rk817->retained_clock[0] || rk817->retained_clock[1] ||
\t\t rk817->clk_playback > 1 || rk817->clk_capture > 1 ||
\t\t (rk817->component && (!rk817->probe_clock_owned || !rk817->clk_lock_initialized)) ||
\t\t (!rk817->component && (rk817->probe_clock_owned || rk817->clk_playback || rk817->clk_capture)))
\t\tret = -EIO;
\tif (ret < 0) {
\t\tif (!rk817->params_error)
\t\t\trk817->params_error = ret;
\t\trk817_shared_failstop(operation, rk817->params_error);
\t}
\tif (!rk817->component) {
\t\trk817->terminal_done = true; /* An unprobed instance owns no codec/clock borrow. */
\t\tgoto out;
\t}
\tret = rk817_shared_power_down(rk817->component, RK817_CODEC_ALL);
\tif (ret < 0) {
\t\trk817->params_error = ret;
\t\trk817_shared_failstop(operation, ret);
\t}
\tmutex_lock(&rk817->clk_lock);
\tif (rk817->clk_playback)
\t\tclk_disable_unprepare(rk817->mclk);
\tif (rk817->clk_capture)
\t\tclk_disable_unprepare(rk817->mclk);
\tif (rk817->probe_clock_owned)
\t\tclk_disable_unprepare(rk817->mclk);
\trk817->clk_playback = 0;
\trk817->clk_capture = 0;
\trk817->probe_clock_owned = false;
\trk817->playback_path = OFF;
\trk817->capture_path = MIC_OFF;
\tmutex_unlock(&rk817->clk_lock);
\trk817->terminal_done = true;
out:
\tmutex_unlock(&rk817->params_lock);
}

static int rk817_shared_probe(struct snd_soc_component *component)
{
\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);
\tstruct snd_soc_dai_params_state *p = &rk817->shared_params;
\tunsigned int chip_name, chip_ver;
\tint ret, cleanup;

\tmutex_lock(&rk817->params_lock);
\tif (rk817->params_error || rk817->mute_io_error || rk817->retained_clock[0] ||
\t    rk817->retained_clock[1] || p->pending || p->owner[0] || p->owner[1] ||
\t    rk817->shared_open[0] || rk817->shared_open[1]) {
\t\tret = rk817->params_error ? rk817->params_error : -EBUSY;
\t\tgoto out;
\t}
\tif (rk817->component || rk817->probe_clock_owned || rk817->clk_playback ||
\t    rk817->clk_capture || rk817->clk_lock_initialized ||
\t    (rk817->terminal_started && !rk817->terminal_done)) {
\t\tret = -EBUSY;
\t\tgoto out;
\t}
\t/* Only a fully detached healthy instance can begin a new component lifetime. */
\trk817->terminal_started = false;
\trk817->terminal_done = false;
\tmutex_init(&rk817->clk_lock);
\trk817->clk_lock_initialized = true;
\tsnd_soc_component_init_regmap(component, rk817->regmap);
\trk817->component = component;
\tret = regmap_read(rk817->regmap, RK817_PMIC_CHIP_NAME, &chip_name);
\tif (ret < 0)
\t\tgoto detach;
\tret = regmap_read(rk817->regmap, RK817_PMIC_CHIP_VER, &chip_ver);
\tif (ret < 0)
\t\tgoto detach;
\trk817->chip_ver = chip_ver & 0x0f;
\tret = clk_prepare_enable(rk817->mclk);
\tif (ret < 0)
\t\tgoto detach;
\trk817->probe_clock_owned = true;
\tret = rk817_reset(component);
\tif (ret < 0) {
\t\trk817->params_error = ret;
\t\trk817_shared_failstop("probe reset", ret);
\t}
\tret = snd_soc_add_component_controls(component, rk817_snd_path_controls,
\t\t\t\t\t     ARRAY_SIZE(rk817_snd_path_controls));
\tif (ret < 0) {
\t\tcleanup = rk817_shared_power_down(component, RK817_CODEC_ALL);
\t\tif (cleanup < 0) {
\t\t\t/* The controls failure remains first; cleanup cannot establish recovery. */
\t\t\trk817->params_error = ret;
\t\t\trk817_shared_failstop("probe controls cleanup", ret);
\t\t}
\t\tmutex_lock(&rk817->clk_lock);
\t\tclk_disable_unprepare(rk817->mclk);
\t\trk817->probe_clock_owned = false;
\t\tmutex_unlock(&rk817->clk_lock);
\t\tgoto detach;
\t}
\tret = 0;
\tgoto out;
detach:
\tcomponent->regmap = NULL;
\trk817->component = NULL;
\tmutex_destroy(&rk817->clk_lock);
\trk817->clk_lock_initialized = false;
out:
\tmutex_unlock(&rk817->params_lock);
\treturn ret;
}

'''


def gate_int(source, name):
    old = function(source, name)
    new = replace(old, '\tmutex_lock(&rk817->params_lock);', '''\tmutex_lock(&rk817->params_lock);
\tif (rk817->terminal_started) {
\t\tmutex_unlock(&rk817->params_lock);
\t\treturn -ESHUTDOWN;
\t}''')
    return replace(source, old, new)


def main():
    out = HERE / 'source-v4'
    shutil.copytree(HERE / 'source-v3', out)
    codec = (out / CODEC).read_text()
    old_codec = codec
    codec = replace(codec, '\tbool retained_clock[2];', '''\tbool retained_clock[2];
\tbool terminal_started;
\tbool terminal_done;
\tbool probe_clock_owned;
\tbool clk_lock_initialized;''')
    old = function(codec, 'rk817_shared_path_config')
    codec = replace(codec, old, replace(old, '\tint ret;\n', '''\tint ret;

\tif (rk817->terminal_started)
\t\treturn -ESHUTDOWN;
'''))
    old = function(codec, 'rk817_resume_path_put')
    codec = replace(codec, old, replace(old, '\t\tif (value < 0 || value > 1)', '''\t\tif (rk817->terminal_started)
\t\t\tret = -ESHUTDOWN;
\t\telse if (value < 0 || value > 1)'''))
    for kind in ['playback', 'capture', 'resume']:
        name = 'rk817_' + kind + '_path_get'
        old = function(codec, name)
        new = replace(old, '''\tif (rk817->shared_params_enabled)
\t\tmutex_lock(&rk817->params_lock);''', '''\tif (rk817->shared_params_enabled) {
\t\tmutex_lock(&rk817->params_lock);
\t\tif (rk817->terminal_started) {
\t\t\tmutex_unlock(&rk817->params_lock);
\t\t\treturn -ESHUTDOWN;
\t\t}
\t}''')
        codec = replace(codec, old, new)
    for name in ['rk817_shared_startup', 'rk817_shared_begin', 'rk817_shared_reuse',
                 'rk817_shared_commit', 'rk817_shared_free_check', 'rk817_shared_free',
                 'rk817_shared_sysclk', 'rk817_shared_hw_params', 'rk817_shared_set_fmt',
                 'rk817_shared_mute']:
        codec = gate_int(codec, name)
    for name in ['rk817_shared_abort', 'rk817_shared_fault', 'rk817_shared_shutdown']:
        old = function(codec, name)
        new = replace(old, '\tmutex_lock(&rk817->params_lock);', '''\tmutex_lock(&rk817->params_lock);
\tif (rk817->terminal_started) {
\t\tmutex_unlock(&rk817->params_lock);
\t\treturn;
\t}''')
        codec = replace(codec, old, new)
    # Direct component PM does not bypass the card-level unsupported profile gate.
    old = function(codec, 'rk817_suspend')
    new = replace(old, '{\n', '''{
\tstruct rk817_codec_priv *rk817 = snd_soc_component_get_drvdata(component);

\tif (rk817->shared_params_enabled) {
\t\tint ret;

\t\tmutex_lock(&rk817->params_lock);
\t\tret = rk817->terminal_started ? -ESHUTDOWN : -EOPNOTSUPP;
\t\tmutex_unlock(&rk817->params_lock);
\t\treturn ret;
\t}
''')
    codec = replace(codec, old, new)
    old = function(codec, 'rk817_resume')
    new = replace(old, '\n\tif (rk817->resume_path)', '''
\tif (rk817->shared_params_enabled) {
\t\tint ret;

\t\tmutex_lock(&rk817->params_lock);
\t\tret = rk817->terminal_started ? -ESHUTDOWN : -EOPNOTSUPP;
\t\tmutex_unlock(&rk817->params_lock);
\t\treturn ret;
\t}

\tif (rk817->resume_path)''')
    codec = replace(codec, old, new)
    codec = replace(codec, 'static int rk817_probe(', HELPERS + 'static int rk817_probe(')
    old = function(codec, 'rk817_probe')
    new = replace(old, '''\tif (!rk817)
\t\treturn -EINVAL;''', '''\tif (!rk817)
\t\treturn -EINVAL;
\tif (rk817->shared_params_enabled)
\t\treturn rk817_shared_probe(component);''')
    codec = replace(codec, old, new)
    old = function(codec, 'rk817_remove')
    marker = '\n\trk817_codec_power_down(component, RK817_CODEC_ALL);'
    checked_remove = '''
\tif (rk817->shared_params_enabled) {
\t\trk817_shared_quiesce(rk817, "component remove");
\t\tmutex_lock(&rk817->params_lock);
\t\tcomponent->regmap = NULL;
\t\trk817->component = NULL;
\t\tif (rk817->clk_lock_initialized) {
\t\t\tmutex_destroy(&rk817->clk_lock);
\t\t\trk817->clk_lock_initialized = false;
\t\t}
\t\tmutex_unlock(&rk817->params_lock);
\t\treturn;
\t}
'''
    codec = replace(codec, old, replace(old, marker, checked_remove + marker))
    old = function(codec, 'rk817_platform_remove')
    new = replace(old, '{\n', '''{
\tstruct rk817_codec_priv *rk817 = dev_get_drvdata(&pdev->dev);

\t/* Reject unsafe teardown before ASoC unregisters DAIs or frees any borrow. */
\tif (rk817 && rk817->shared_params_enabled)
\t\trk817_shared_quiesce(rk817, "platform remove");
''')
    codec = replace(codec, old, new)
    old = function(codec, 'rk817_platform_shutdown')
    new = replace(old, '\n\tif (rk817 && rk817->component)', '''
\tif (rk817 && rk817->shared_params_enabled) {
\t\trk817_shared_quiesce(rk817, "platform shutdown");
\t\treturn;
\t}

\tif (rk817 && rk817->component)''')
    codec = replace(codec, old, new)
    (out / CODEC).write_text(codec)
    cpu = (out / CPU).read_text()
    old_cpu = cpu
    old = function(cpu, 'i2s_checked_runtime_suspend')
    new = replace(old, '''\tif (i2s_tdm->shared_params_enabled &&
\t    (i2s_tdm->shared_params.pending || i2s_tdm->shared_params.owner[0] ||
\t     i2s_tdm->shared_params.owner[1]))
\t\tret = -EBUSY;
\telse if (i2s_tdm->runtime_error && !i2s_tdm->shutting_down)
\t\tret = i2s_tdm->runtime_error;''', '''\tif (i2s_tdm->runtime_error && !i2s_tdm->shutting_down)
\t\tret = i2s_tdm->runtime_error;
\telse if (i2s_tdm->shared_params_enabled &&
\t\t (i2s_tdm->shared_params.pending || i2s_tdm->shared_params.owner[0] ||
\t\t  i2s_tdm->shared_params.owner[1]))
\t\tret = -EBUSY;''')
    cpu = replace(cpu, old, new)
    (out / CPU).write_text(cpu)
    files = {}
    patch = []
    for rel, before, after in [(CODEC, old_codec, codec), (CPU, old_cpu, cpu)]:
        files[rel] = {'baseline_sha256': sha(before.encode()), 'candidate_sha256': sha(after.encode()),
                      'bytes': len(after.encode())}
        patch.append(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                fromfile='a/' + rel, tofile='b/' + rel)))
    data = ''.join(patch)
    (HERE / 'terminal-private-v4.patch').write_text(data)
    (HERE / 'source-manifest-v4.json').write_text(json.dumps({
        'scope': 'TERMINAL_PRIVATE_INCREMENT_OVER_SHARED_IO_V3_NO_BOARD',
        'base_source_manifest_sha256': sha((HERE / 'source-manifest-v3.json').read_bytes()),
        'generator_sha256': sha(Path(__file__).read_bytes()), 'files': files,
        'patch_sha256': sha(data.encode()),
    }, indent=2) + '\n')
    print(json.dumps({'sources': len(files), 'patch_bytes': len(data), 'compiler_executed': False}))


if __name__ == '__main__':
    main()
