#!/usr/bin/env python3
"""Fresh terminal source with actual ASoC file drain; preserves v3/v4 snapshots."""
import difflib
import importlib.util
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SDK = HERE.parents[2] / '.deps/kernel-source/aiot-3568pq-audio-v4'
PARAMS = HERE.parent / 'full-duplex-params-candidate-v1'
spec = importlib.util.spec_from_file_location('source_utils', PARAMS / 'model-v4/source_utils.py')
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)
function, replace, sha = utils.function, utils.replace, utils.sha
CODEC = 'sound/soc/codecs/rk817_codec.c'
CORE = 'sound/soc/soc-core.c'
HEADER = 'include/sound/soc.h'

CORE_HELPER = '''/**
 * snd_soc_component_shutdown_card - drain and unbind a component's card
 * @dev: component device, whose driver lifetime the caller owns
 * @driver: exact registered component driver
 * @timeout_ms: file release wait, between 1 and 5000 milliseconds
 *
 * Process context only. Opt-in shutdown callers must release their private
 * locks before entry. client_mutex stabilizes component/card just as in
 * snd_soc_unregister_card(); card->mutex must not be held while files drain
 * because DPCM close needs it. Disconnect closes admission but has the normal
 * ALSA disconnect side effects. A timeout keeps the card/resources allocated.
 * The existing delayed-work flush and card free retain their framework waits.
 */
int snd_soc_component_shutdown_card(struct device *dev,
\t\t\t const struct snd_soc_component_driver *driver,
\t\t\t unsigned int timeout_ms)
{
\tstruct snd_soc_component *component;
\tstruct snd_soc_card *card;
\tstruct snd_card *snd_card;
\tlong remaining;
\tint ret = 0;

\tif (!dev || !driver || !timeout_ms || timeout_ms > 5000)
\t\treturn -EINVAL;
\tmight_sleep();
\tmutex_lock(&client_mutex);
\tcomponent = snd_soc_lookup_component_nolocked(dev, driver->name);
\tif (!component)
\t\tgoto out;
\tif (component->driver != driver) {
\t\tret = -EINVAL;
\t\tgoto out;
\t}
\tcard = component->card;
\tif (!card)
\t\tgoto out;
\tif (!card->instantiated || !card->snd_card) {
\t\tret = -EINVAL;
\t\tgoto out;
\t}
\tsnd_card = card->snd_card;
\tret = snd_card_disconnect(snd_card);
\tif (ret < 0)
\t\tgoto out;
\tspin_lock_irq(&snd_card->files_lock);
\tremaining = wait_event_lock_irq_timeout(snd_card->remove_sleep,
\t\t\t\t\t      list_empty(&snd_card->files_list),
\t\t\t\t\t      snd_card->files_lock,
\t\t\t\t\t      msecs_to_jiffies(timeout_ms));
\tif (!remaining && !list_empty(&snd_card->files_list))
\t\tret = -ETIMEDOUT;
\tspin_unlock_irq(&snd_card->files_lock);
\tif (ret < 0)
\t\tgoto out;
\t/* Same internal cleanup as component removal; no recursive client lock. */
\tsnd_soc_unbind_card(card, false);
out:
\tmutex_unlock(&client_mutex);
\treturn ret;
}
EXPORT_SYMBOL_GPL(snd_soc_component_shutdown_card);

'''

CHECK = '''/* This check is not a PCM drain: release remains allowed until core disconnect. */
static int rk817_shared_terminal_check(struct rk817_codec_priv *rk817, bool shutdown)
{
\tint ret = 0;

\tmutex_lock(&rk817->params_lock);
\tif (rk817->params_error)
\t\tret = rk817->params_error;
\telse if (rk817->mute_io_error)
\t\tret = rk817->mute_io_error;
\telse if (rk817->retained_clock[0] || rk817->retained_clock[1] ||
\t\t rk817->clk_playback > 1 || rk817->clk_capture > 1)
\t\tret = -EIO;
\tif (ret < 0 && !rk817->params_error)
\t\trk817->params_error = ret;
\tif (!ret && shutdown)
\t\trk817->shutdown_started = true;
\tmutex_unlock(&rk817->params_lock);
\treturn ret;
}

'''


def main():
    out = HERE / 'source-v5'
    shutil.copytree(HERE / 'source-v4', out)
    codec = (out / CODEC).read_text()
    codec = replace(codec, '\tbool terminal_started;', '\tbool shutdown_started;\n\tbool terminal_started;')
    codec = replace(codec, '/* params_lock drains all checked borrowers before terminal I/O or clock release. */',
                    '''/* Called after ASoC file drain, or with no bound card/component borrow.
 * params_lock then drains local checked bodies before terminal I/O/lease release.
 */''')
    codec = replace(codec, 'static int rk817_shared_probe(', CHECK + 'static int rk817_shared_probe(')
    for name in ['rk817_shared_startup', 'rk817_shared_probe']:
        old = function(codec, name)
        marker = '\tmutex_lock(&rk817->params_lock);'
        new = replace(old, marker, marker + '''
\tif (rk817->shutdown_started) {
\t\tmutex_unlock(&rk817->params_lock);
\t\treturn -ESHUTDOWN;
\t}''')
        codec = replace(codec, old, new)
    old = function(codec, 'rk817_platform_remove')
    codec = replace(codec, old, '''static int rk817_platform_remove(struct platform_device *pdev)
{
\tstruct rk817_codec_priv *rk817 = dev_get_drvdata(&pdev->dev);
\tint ret;

\tif (rk817 && rk817->shared_params_enabled) {
\t\tret = rk817_shared_terminal_check(rk817, false);
\t\tif (ret < 0)
\t\t\trk817_shared_failstop("platform remove", ret);
\t}
\t/* Actual core cleanup disconnects/drains files before component.remove. */
\tsnd_soc_unregister_component(&pdev->dev);
\treturn 0;
}''')
    old = function(codec, 'rk817_platform_shutdown')
    codec = replace(codec, old, '''static void rk817_platform_shutdown(struct platform_device *pdev)
{
\tstruct rk817_codec_priv *rk817 = dev_get_drvdata(&pdev->dev);
\tint ret;

\tif (rk817 && rk817->shared_params_enabled) {
\t\tret = rk817_shared_terminal_check(rk817, true);
\t\tif (ret < 0)
\t\t\trk817_shared_failstop("platform shutdown", ret);
\t\t/* No private lock is held while core waits for complete PCM release. */
\t\tret = snd_soc_component_shutdown_card(&pdev->dev, &soc_codec_dev_rk817, 5000);
\t\tif (ret < 0) {
\t\t\tmutex_lock(&rk817->params_lock);
\t\t\tif (!rk817->params_error)
\t\t\t\trk817->params_error = ret;
\t\t\tret = rk817->params_error;
\t\t\tmutex_unlock(&rk817->params_lock);
\t\t\trk817_shared_failstop("platform shutdown drain", ret);
\t\t}
\t\t/* Bound card removal already did this; unbound/unprobed is idempotent. */
\t\trk817_shared_quiesce(rk817, "platform shutdown complete");
\t\treturn;
\t}

\tif (rk817 && rk817->component)
\t\trk817_codec_power_down(rk817->component, RK817_CODEC_ALL);
}''')
    (out / CODEC).write_text(codec)
    core = (out / CORE).read_text()
    core = replace(core, 'EXPORT_SYMBOL_GPL(snd_soc_unregister_card);\n',
                   'EXPORT_SYMBOL_GPL(snd_soc_unregister_card);\n\n' + CORE_HELPER)
    (out / CORE).write_text(core)
    original_header = (SDK / HEADER).read_text()
    header = replace(original_header, 'void snd_soc_unregister_component(struct device *dev);',
                     '''void snd_soc_unregister_component(struct device *dev);
/* Process-only opt-in shutdown: closes admission, waits for files, then unbinds. */
int snd_soc_component_shutdown_card(struct device *dev,
\t\t\t const struct snd_soc_component_driver *driver,
\t\t\t unsigned int timeout_ms);''')
    (out / HEADER).write_text(header)
    files, patches = {}, []
    for path in sorted(out.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(out).as_posix()
        before = original_header if rel == HEADER else (HERE / 'source-v3' / rel).read_text()
        after = path.read_text()
        files[rel] = {'baseline_sha256': sha(before.encode()), 'candidate_sha256': sha(path.read_bytes()),
                      'bytes': path.stat().st_size}
        if before != after:
            patches.append(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                      fromfile='a/' + rel, tofile='b/' + rel)))
    patch = ''.join(patches)
    (HERE / 'terminal-private-v5.patch').write_text(patch)
    (HERE / 'source-manifest-v5.json').write_text(json.dumps({
        'scope': 'OPT_IN_TERMINAL_FILE_DRAIN_INCREMENT_OVER_SHARED_IO_V3_NO_BOARD',
        'base_source_manifest_sha256': sha((HERE / 'source-manifest-v3.json').read_bytes()),
        'generator_sha256': sha(Path(__file__).read_bytes()), 'files': files,
        'patch_sha256': sha(patch.encode()),
    }, indent=2) + '\n')
    print(json.dumps({'source': 'source-v5', 'files': len(files), 'patch_bytes': len(patch)}))


if __name__ == '__main__':
    main()
