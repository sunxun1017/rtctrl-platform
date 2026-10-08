#!/usr/bin/env python3
"""Bounded five-source private patch; never writes the accepted kernel tree."""
import argparse, difflib, hashlib, json, re
from pathlib import Path
HERE = Path(__file__).resolve().parent
def sha(data): return hashlib.sha256(data).hexdigest()
def one(text, old, new):
    if text.count(old) != 1: raise ValueError('Expected one replacement: ' + old[:100])
    return text.replace(old, new)
def function(text, name):
    m = re.search(r'^[A-Za-z_][A-Za-z_0-9 \t*\n]*\b' + re.escape(name) + r'\([^;{}]*?\)\s*\{', text, re.M)
    if not m: raise ValueError('Missing function ' + name)
    depth = 0
    for i in range(text.index('{', m.start()), len(text)):
        depth += (text[i] == '{') - (text[i] == '}')
        if not depth: return text[m.start():i+1]
    raise ValueError('Unclosed function ' + name)
def replace_function(text, name, callback):
    old = function(text, name)
    return one(text, old, callback(old))
def inc(name): return (HERE / name).read_text()
def main():
    inputs = json.loads((HERE/'inputs-v1/manifest.json').read_text())
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', type=int, required=True)
    args = parser.parse_args()
    if args.version < 2: raise ValueError('Preserve initial v1 draft')
    out = HERE / ('source-v' + str(args.version))
    if out.exists(): raise ValueError('Fresh candidate output required')
    sources = {}
    for rel, item in inputs['inputs'].items():
        p = HERE/'inputs-v1'/rel
        if p.is_symlink() or sha(p.read_bytes()) != item['sha256']: raise ValueError('Input drift ' + rel)
        sources[rel] = p.read_text()
    h = 'include/sound/soc-dai.h'; t = sources[h]
    t = one(t, 'struct snd_soc_dai_ops {', inc('header-state.inc')+'\nstruct snd_soc_dai_ops {')
    t = one(t, '\tunsigned int no_capture_mute:1;\n};', '''\tunsigned int no_capture_mute:1;

	/* Optional whole-chain, explicitly opt-in parameter ownership transaction. */
	int (*hw_params_begin)(struct snd_pcm_substream *, struct snd_pcm_hw_params *,
			       struct snd_soc_dai *, u64 *cookie);
	int (*hw_params_commit)(struct snd_pcm_substream *, struct snd_soc_dai *, u64 cookie);
	void (*hw_params_abort)(struct snd_pcm_substream *, struct snd_soc_dai *,
			       u64 cookie, int first_error, bool shared_io_possible);
	int (*hw_params_reuse)(struct snd_pcm_substream *, struct snd_soc_dai *);
	int (*hw_params_free_check)(struct snd_pcm_substream *, struct snd_soc_dai *);
	void (*hw_params_fault)(struct snd_soc_dai *, int first_errno);
};''')
    t = one(t, 'static inline struct snd_soc_pcm_stream *', inc('header-helpers.inc')+'\nstatic inline struct snd_soc_pcm_stream *')
    sources[h] = t
    h = 'sound/soc/soc-pcm.c'; t = sources[h]
    old = function(t, 'soc_pcm_hw_params')
    new = one(old, 'int i, ret = 0;', 'int i, ret = 0, managed;')
    new = one(new, '\tret = snd_soc_link_hw_params(substream, params);', '''\tmanaged = soc_pcm_params_managed(rtd);
	if (managed < 0) {
		ret = managed;
		goto out;
	}
	if (managed) {
		ret = soc_pcm_hw_params_transaction(substream, params);
		goto out;
	}

	ret = snd_soc_link_hw_params(substream, params);''')
    t = one(t, old, inc('core-params.inc')+'\n'+new)
    old = function(t, 'soc_pcm_hw_free')
    new = one(old, 'int i, ret = 0;', 'int i, ret = 0, managed;')
    new = one(new, '\t/* clear the corresponding DAIs parameters when going to be inactive */', '''\tmanaged = soc_pcm_params_managed(rtd);
	if (managed < 0) {
		ret = managed;
		goto out;
	}
	if (managed) {
		ret = soc_pcm_hw_free_transaction(substream);
		goto out;
	}

	/* clear the corresponding DAIs parameters when going to be inactive */''')
    new = one(new, '\tmutex_unlock(&rtd->card->pcm_mutex);', 'out:\n\tmutex_unlock(&rtd->card->pcm_mutex);')
    t = one(t, old, inc('core-free.inc')+'\n'+new)
    sources[h] = t
    h = 'sound/soc/generic/simple-card-utils.c'; t = sources[h]
    def machine(old):
        old = one(old, '\tint ret;', '\tint ret, cpu_reuse, codec_reuse;')
        return one(old, '\tif (mclk_fs) {', '''\tif (snd_soc_dai_hw_params_any(cpu_dai) || snd_soc_dai_hw_params_any(codec_dai)) {
		if (rtd->num_cpus != 1 || rtd->num_codecs != 1 ||
		    !snd_soc_dai_hw_params_managed(cpu_dai) ||
		    !snd_soc_dai_hw_params_managed(codec_dai) || mclk_fs != 256 ||
		    params_rate(params) != 48000 || params_channels(params) != 2 ||
		    params_format(params) != SNDRV_PCM_FORMAT_S16_LE)
			return -EINVAL;
		cpu_reuse = snd_soc_dai_hw_params_reuse(cpu_dai, substream);
		codec_reuse = snd_soc_dai_hw_params_reuse(codec_dai, substream);
		if (cpu_reuse < 0 || codec_reuse < 0 || cpu_reuse != codec_reuse)
			return cpu_reuse < 0 ? cpu_reuse : codec_reuse < 0 ? codec_reuse : -EINVAL;
		if (cpu_reuse)
			return 0; /* No shared CCF query/write or public sysclk request. */
	}

	if (mclk_fs) {''')
    sources[h] = replace_function(t, 'asoc_simple_hw_params', machine)
    h = 'sound/soc/rockchip/rockchip_i2s_tdm.c'; t = sources[h]
    t = one(t, '\tbool checked_lifecycle;', '''\tbool shared_params_enabled;
	struct snd_soc_dai_params_state shared_params;
	unsigned int shared_dai_fmt, shared_prepared;
	bool checked_lifecycle;''')
    t = one(t, 'static int i2s_checked_hw_params(', inc('cpu-params.inc')+'\nstatic int i2s_checked_hw_params(')
    def start(old):
        return one(old, '\tif (i2s_tdm->started & bit)', '''\tif (i2s_tdm->shared_params_enabled &&
	    (i2s_tdm->shared_params.owner[stream] != i2s_tdm->substreams[stream] ||
	     !i2s_tdm->shared_params.owner[stream] || !(i2s_tdm->shared_prepared & bit)))
		return -EINVAL;
	if (i2s_tdm->started & bit)''')
    t = replace_function(t, 'i2s_checked_start_locked', start)
    def prepare(old):
        old = one(old, '\tif (!ret && !READ_ONCE(i2s_tdm->ready))', '''\tif (!ret && i2s_tdm->shared_params_enabled &&
	    ((substream->stream != 0 && substream->stream != 1) ||
	     i2s_tdm->shared_params.owner[substream->stream] != substream))
		ret = -EINVAL;
	if (!ret && !READ_ONCE(i2s_tdm->ready))''')
        return one(old, '\tspin_unlock_irqrestore(&i2s_tdm->lock, flags);', '''\tif (!ret && i2s_tdm->shared_params_enabled)
		i2s_tdm->shared_prepared |= BIT(substream->stream);
	spin_unlock_irqrestore(&i2s_tdm->lock, flags);''')
    t = replace_function(t, 'i2s_checked_prepare', prepare)
    def component(old):
        return one(old, '\t\tspin_unlock_irqrestore(&i2s_tdm->lock, flags);', '''\t\telse if (i2s_tdm->shared_params_enabled &&
			 (i2s_tdm->shared_params.owner[substream->stream] != substream ||
			  !(i2s_tdm->shared_prepared & BIT(substream->stream))))
			ret = -EINVAL;
		spin_unlock_irqrestore(&i2s_tdm->lock, flags);''')
    t = replace_function(t, 'i2s_checked_component_trigger', component)
    def shutdown(old):
        return one(old, '\t\tif (ret)\n\t\t\tdev_err', '''\t\tif (!ret && i2s_tdm->shared_params_enabled)
			ret = i2s_shared_free(substream, dai);
		if (ret)
			dev_err''')
    t = replace_function(t, 'rockchip_i2s_tdm_shutdown', shutdown)
    anchor = 'static const struct snd_soc_component_driver rockchip_i2s_tdm_component = {'
    checked_ops = '''static const struct snd_soc_dai_ops rockchip_i2s_tdm_shared_ops = {
	.startup = rockchip_i2s_tdm_startup,
	.shutdown = rockchip_i2s_tdm_shutdown,
	.prepare = i2s_checked_prepare,
	.hw_params = i2s_shared_hw_params,
	.hw_free = i2s_shared_free,
	.set_sysclk = i2s_shared_sysclk,
	.set_fmt = i2s_shared_set_fmt,
	.set_tdm_slot = i2s_shared_tdm_slot,
	.trigger = rockchip_i2s_tdm_trigger,
	.hw_params_begin = i2s_shared_begin,
	.hw_params_commit = i2s_shared_commit,
	.hw_params_abort = i2s_shared_abort,
	.hw_params_reuse = i2s_shared_reuse,
	.hw_params_free_check = i2s_shared_free_check,
	.hw_params_fault = i2s_shared_fault,
};

'''
    t = one(t, anchor, checked_ops+anchor)
    t = one(t, '\ti2s_tdm->checked_lifecycle = i2s_checked_profile(pdev);', '''\ti2s_tdm->checked_lifecycle = i2s_checked_profile(pdev);
	i2s_tdm->shared_params_enabled = of_property_read_bool(node,
						"rockchip,checked-shared-params-48k");
	if (i2s_tdm->shared_params_enabled) {
		if (!i2s_tdm->checked_lifecycle)
			return -EINVAL;
		/* soc_dai is already a devm-owned per-probe copy. */
		soc_dai->ops = &rockchip_i2s_tdm_shared_ops;
	}''')
    sources[h] = t
    h = 'sound/soc/codecs/rk817_codec.c'; t = sources[h]
    t = one(t, '\tstruct mutex clk_lock;', '''\tstruct mutex clk_lock;
	struct mutex params_lock;
	struct snd_soc_dai_params_state shared_params;
	bool shared_params_enabled;
	unsigned int shared_dai_fmt;
	int params_error;''')
    t = one(t, '\tstruct snd_soc_dai_params_state shared_params;', '\tstruct snd_soc_dai_params_state shared_params;\n\tstruct snd_pcm_substream *shared_open[2];')
    anchor = 'static struct snd_soc_dai_driver rk817_dai[] = {'
    ops = '''static const struct snd_soc_dai_ops rk817_shared_dai_ops = {
	.startup = rk817_shared_startup,
	.hw_params = rk817_shared_hw_params,
	.hw_free = rk817_shared_free,
	.set_fmt = rk817_shared_set_fmt,
	.set_sysclk = rk817_shared_sysclk,
	.mute_stream = rk817_digital_mute,
	.shutdown = rk817_shared_shutdown,
	.hw_params_begin = rk817_shared_begin,
	.hw_params_commit = rk817_shared_commit,
	.hw_params_abort = rk817_shared_abort,
	.hw_params_reuse = rk817_shared_reuse,
	.hw_params_free_check = rk817_shared_free_check,
	.hw_params_fault = rk817_shared_fault,
};

'''
    t = one(t, anchor, inc('codec-params.inc')+'\n'+ops+anchor)
    # The real parse helper owns/puts this node; retain that lifetime.
    t = one(t, '\trk817->hp_ctl_gpio = devm_gpiod_get_optional', '''\trk817->shared_params_enabled = of_property_read_bool(node,
						  "rockchip,checked-shared-params-48k");

	rk817->hp_ctl_gpio = devm_gpiod_get_optional''')
    def probe(old):
        old = one(old, '\tint ret;', '\tstruct snd_soc_dai_driver *dais = rk817_dai;\n\tint ret;')
        old = one(old, '\tplatform_set_drvdata(pdev, rk817_codec_data);', '\tmutex_init(&rk817_codec_data->params_lock);\n\tplatform_set_drvdata(pdev, rk817_codec_data);')
        old = one(old, '\tret = devm_snd_soc_register_component', '''\tif (rk817_codec_data->shared_params_enabled) {
		dais = devm_kmemdup(&pdev->dev, rk817_dai, sizeof(rk817_dai), GFP_KERNEL);
		if (!dais) {
			ret = -ENOMEM;
			goto err_;
		}
		/* Hifi and voice share the state; checked voice entrypoints reject id. */
		dais[0].ops = &rk817_shared_dai_ops;
		dais[1].ops = &rk817_shared_dai_ops;
	}
	ret = devm_snd_soc_register_component''')
        return one(old, 'rk817_dai, ARRAY_SIZE(rk817_dai)', 'dais, ARRAY_SIZE(rk817_dai)')
    sources[h] = replace_function(t, 'rk817_platform_probe', probe)
    patch = []
    manifest = {'scope': 'PRIVATE_FIVE_SOURCE_CANDIDATE_NO_BUILD_NO_DT_NO_BOARD', 'input_manifest_sha256': sha((HERE/'inputs-v1/manifest.json').read_bytes()), 'files': {}, 'changed_functions': {}}
    for rel, text in sources.items():
        original = (HERE/'inputs-v1'/rel).read_text()
        path = out/rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        if path.read_text() != text: raise ValueError('Candidate readback')
        manifest['files'][rel] = {'baseline_sha256': sha(original.encode()), 'candidate_sha256': sha(text.encode()), 'bytes': len(text.encode())}
        patch.extend(difflib.unified_diff(original.splitlines(True), text.splitlines(True), fromfile='a/'+rel, tofile='b/'+rel))
        names = re.findall(r'^[A-Za-z_][A-Za-z_0-9 \t*\n]*\b(\w+)\([^;{}]*?\)\s*\{', text, re.M)
        for name in dict.fromkeys(names):
            body = function(text, name)
            try: old = function(original, name)
            except ValueError: old = None
            if old != body:
                manifest['changed_functions'][rel+':'+name] = {'candidate_sha256': sha(body.encode()), 'baseline_sha256': sha(old.encode()) if old else None, 'bytes': len(body.encode())}
    patch_path = HERE / ('shared-params-private-v' + str(args.version) + '.patch')
    patch_path.write_text(''.join(patch))
    manifest['patch_sha256'] = sha(patch_path.read_bytes())
    manifest['generator_sha256'] = sha(Path(__file__).read_bytes())
    manifest_path = HERE / ('source-manifest-v' + str(args.version) + '.json')
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    print(json.dumps({'files': len(sources), 'changed_function_identities': len(manifest['changed_functions']), 'manifest_sha256': sha(manifest_path.read_bytes()), 'no_build': True}))
if __name__ == '__main__': main()
