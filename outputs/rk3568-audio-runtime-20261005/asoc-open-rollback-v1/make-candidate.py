#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create four private production sources from SHA-locked baseline inputs."""
import difflib
import importlib.util
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'outputs/rk3568-audio-runtime-20261005/full-duplex-contract-v1'


def main():
    inputs = HERE / 'inputs-v1'
    source = HERE / 'source-v1'
    inputs.mkdir(exist_ok=False)
    source.mkdir(exist_ok=False)
    util_path = BASE / 'model-v5/source_utils.py'
    spec = importlib.util.spec_from_file_location('source_utils', util_path)
    util = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(util)
    function, sha = util.function, util.sha
    baseline = json.loads((BASE / 'model-v5/input-manifest.json').read_text())
    paths = {
        'sound/soc/soc-pcm.c': 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/full-replay/sound/soc/soc-pcm.c',
        'sound/soc/soc-component.c': 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/full-replay/sound/soc/soc-component.c',
        'sound/soc/soc-compress.c': '.deps/kernel-source/aiot-3568pq-audio-v3/sound/soc/soc-compress.c',
        'sound/soc/generic/simple-card-utils.c': '.deps/kernel-source/aiot-3568pq-audio-v2/sound/soc/generic/simple-card-utils.c',
    }
    originals = {}
    input_files = {}
    for target, origin in paths.items():
        path = ROOT / origin
        assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
        data = path.read_bytes()
        assert sha(data) == baseline['input_files'][origin]['sha256']
        snapshot = inputs / Path(target).name
        snapshot.write_bytes(data)
        originals[target] = data.decode()
        input_files[origin] = {'sha256': sha(data), 'snapshot': snapshot.relative_to(HERE).as_posix()}
    for name, path in [('approved-design.md', ROOT / 'docs/superpowers/specs/2026-10-06-rk3568-asoc-open-rollback-design.md'),
                       ('approved-plan.md', ROOT / 'docs/superpowers/plans/2026-10-06-rk3568-asoc-open-rollback.md'),
                       ('baseline-seal.json', BASE / 'sealed-v1/receipt.json'),
                       ('baseline-model-input.json', BASE / 'model-v5/input-manifest.json'),
                       ('source_utils.py', util_path)]:
        data = path.read_bytes()
        (inputs / name).write_bytes(data)
        input_files[path.relative_to(ROOT).as_posix()] = {'sha256': sha(data), 'snapshot': (inputs / name).relative_to(HERE).as_posix()}
    changed = dict(originals)
    pcm = changed['sound/soc/soc-pcm.c']
    old_clean = function(pcm, 'soc_pcm_clean')
    new_clean = '''static void soc_pcm_clean_locked(struct snd_pcm_substream *substream,
				 int rollback)
{
	struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(substream);
	struct snd_soc_dai *dai;
	int i;

	lockdep_assert_held(&rtd->card->pcm_mutex);
	if (!rollback)
		snd_soc_runtime_deactivate(rtd, substream->stream);
	for_each_rtd_dais(rtd, i, dai)
		snd_soc_dai_shutdown(dai, substream, rollback);
	snd_soc_link_shutdown(substream, rollback);
	soc_pcm_components_close(substream, rollback);
	if (!rollback)
		snd_soc_dapm_stream_stop(rtd, substream->stream);
}

static void soc_pcm_clean_post_unlock(struct snd_pcm_substream *substream,
				      int rollback)
{
	struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(substream);
	struct snd_soc_component *component;
	int i;

	/* Only a fully successful get reaches this stage, so this call owns all refs. */
	snd_soc_pcm_component_pm_runtime_put(rtd, substream, rollback);
	for_each_rtd_components(rtd, i, component)
		if (!snd_soc_component_active(component))
			pinctrl_pm_select_sleep_state(component->dev);
}

static int soc_pcm_clean(struct snd_pcm_substream *substream, int rollback)
{
	struct snd_soc_pcm_runtime *rtd = asoc_substream_to_rtd(substream);

	mutex_lock_nested(&rtd->card->pcm_mutex, rtd->card->pcm_subclass);
	soc_pcm_clean_locked(substream, rollback);
	mutex_unlock(&rtd->card->pcm_mutex);
	soc_pcm_clean_post_unlock(substream, rollback);
	return 0;
}'''
    pcm = pcm.replace(old_clean, new_clean, 1)
    old_open = function(pcm, 'soc_pcm_open')
    ending = '''err:
	mutex_unlock(&rtd->card->pcm_mutex);
pm_err:
	if (ret < 0)
		soc_pcm_clean(substream, 1);

	return ret;'''
    replacement = '''err:
	/* Single-pointer startup/open/module marks stay in this transaction. */
	if (ret < 0)
		soc_pcm_clean_locked(substream, 1);
	mutex_unlock(&rtd->card->pcm_mutex);
	if (ret < 0)
		soc_pcm_clean_post_unlock(substream, 1);
	return ret;

pm_err:
	/* A failed get has already returned exactly its local acquired prefix. */
	for_each_rtd_components(rtd, i, component)
		if (!snd_soc_component_active(component))
			pinctrl_pm_select_sleep_state(component->dev);
	return ret;'''
    assert old_open.count(ending) == 1
    pcm = pcm.replace(old_open, old_open.replace(ending, replacement), 1)
    changed['sound/soc/soc-pcm.c'] = pcm
    component = changed['sound/soc/soc-component.c']
    old_get = function(component, 'snd_soc_pcm_component_pm_runtime_get')
    new_get = '''int snd_soc_pcm_component_pm_runtime_get(struct snd_soc_pcm_runtime *rtd,
					 void *stream)
{
	struct snd_soc_component *component, *previous;
	int i, j, ret;

	(void)stream;
	for_each_rtd_components(rtd, i, component) {
		ret = pm_runtime_get_sync(component->dev);
		if (ret < 0 && ret != -EACCES) {
			/* get_sync increments usage even when resume fails. */
			pm_runtime_put_noidle(component->dev);
			/* Each occurrence owns one reference, including repeated devices. */
			for (j = 0; j < i; j++) {
				previous = rtd->components[j];
				pm_runtime_mark_last_busy(previous->dev);
				pm_runtime_put_autosuspend(previous->dev);
			}
			return soc_component_ret(component, ret);
		}
	}
	return 0;
}'''
    old_put = function(component, 'snd_soc_pcm_component_pm_runtime_put')
    new_put = '''void snd_soc_pcm_component_pm_runtime_put(struct snd_soc_pcm_runtime *rtd,
					  void *stream, int rollback)
{
	struct snd_soc_component *component;
	int i;

	/* Callers reach here only after a full successful get for this call. */
	(void)stream;
	(void)rollback;
	for_each_rtd_components(rtd, i, component) {
		pm_runtime_mark_last_busy(component->dev);
		pm_runtime_put_autosuspend(component->dev);
	}
}'''
    component = component.replace(old_get, new_get, 1).replace(old_put, new_put, 1)
    changed['sound/soc/soc-component.c'] = component
    compress = changed['sound/soc/soc-compress.c']
    old_compr = function(compress, 'soc_compr_open')
    assert old_compr.count('if (ret < 0)\n\t\tgoto pm_err;') == 1
    new_compr = old_compr.replace('if (ret < 0)\n\t\tgoto pm_err;', 'if (ret < 0)\n\t\treturn ret;', 1)
    assert new_compr.count('pm_err:\n') == 1
    new_compr = new_compr.replace('pm_err:\n', '', 1)
    changed['sound/soc/soc-compress.c'] = compress.replace(old_compr, new_compr, 1)
    simple = changed['sound/soc/generic/simple-card-utils.c']
    old_shutdown = function(simple, 'asoc_simple_shutdown')
    assert old_shutdown.count('if (dai_props->mclk_fs) {') == 1
    new_shutdown = old_shutdown.replace('if (dai_props->mclk_fs) {',
        'if (dai_props->mclk_fs &&\n\t    !snd_soc_dai_active(asoc_rtd_to_cpu(rtd, 0)) &&\n'
        '\t    !snd_soc_dai_active(asoc_rtd_to_codec(rtd, 0))) {', 1)
    changed['sound/soc/generic/simple-card-utils.c'] = simple.replace(old_shutdown, new_shutdown, 1)
    patch = ''
    files = {}
    for path, text in changed.items():
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        files[path] = {'sha256': sha(target.read_bytes()), 'original_sha256': sha(originals[path].encode())}
        patch += ''.join(difflib.unified_diff(originals[path].splitlines(True), text.splitlines(True),
                                             fromfile='a/' + path, tofile='b/' + path))
    (HERE / 'candidate-v1.patch').write_text(patch)
    receipt = {'schema': 'rk3568-asoc-open-rollback-source-v1', 'files': files,
               'inputs': input_files, 'patch_sha256': sha((HERE / 'candidate-v1.patch').read_bytes()),
               'headers_struct_ABI_changed': False, 'CPU_v12_modified': False,
               'START_gates_modified': False, 'board_tested': False, 'public_patch_published': False}
    (HERE / 'source-manifest-v1.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'sources': files, 'patch_sha256': receipt['patch_sha256']}))


if __name__ == '__main__':
    main()
