#!/usr/bin/env python3
"""Snapshot finite ordinary design inputs and source function identities; no model/build."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat

HERE = Path(__file__).resolve().parent
AUDIO = HERE.parent
ROOT = AUDIO.parents[1]
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v4'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(path):
    if not path.is_relative_to(ROOT) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Ordinary input required: ' + str(path))
    ancestor = path.parent
    while True:
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError('Nonordinary ancestor: ' + str(ancestor))
        if ancestor == ROOT:
            break
        ancestor = ancestor.parent
    return {'bytes': path.stat().st_size, 'mode': stat.S_IMODE(path.stat().st_mode), 'sha256': sha(path)}


def identify_functions(path, names):
    text = path.read_text()
    rows = {}
    for name in names:
        match = re.search(r'^[A-Za-z_][A-Za-z_0-9 \t*]*\b' + name + r'\([^;{}]*?\)\s*\{', text, re.M)
        if match is None:
            raise ValueError('Function missing: ' + name)
        depth = 0
        for i in range(text.index('{', match.start()), len(text)):
            depth += (text[i] == '{') - (text[i] == '}')
            if depth == 0:
                payload = text[match.start():i + 1].encode()
                rows[name] = {'line': text.count('\n', 0, match.start()) + 1,
                    'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
                break
        else:
            raise ValueError('Unclosed function: ' + name)
    return rows


def main():
    out = HERE / 'inputs-v1'
    out.mkdir(exist_ok=False)
    source_manifest = AUDIO / 'asoc-open-rollback-v1/source-manifest-v1.json'
    declared = json.loads(source_manifest.read_text())['files']
    inventory_path = AUDIO / 'build/integration-v4/integrated-source-inventory.json'
    inventory = json.loads(inventory_path.read_text())
    files = {}
    bindings = {}
    groups = {
        'soc-pcm.c': ('asoc-open-rollback-v1/source-v1/sound/soc/soc-pcm.c', 'sound/soc/soc-pcm.c',
            ['soc_pcm_params_symmetry', 'soc_pcm_codec_params_fixup', 'soc_pcm_hw_params', 'soc_pcm_hw_free',
             'soc_pcm_clean_locked', 'soc_pcm_clean_post_unlock', 'soc_pcm_open', 'soc_pcm_prepare']),
        'soc-component.c': ('asoc-open-rollback-v1/source-v1/sound/soc/soc-component.c', 'sound/soc/soc-component.c',
            ['snd_soc_pcm_component_hw_params', 'snd_soc_pcm_component_hw_free',
             'snd_soc_pcm_component_pm_runtime_get', 'snd_soc_pcm_component_pm_runtime_put']),
        'soc-compress.c': ('asoc-open-rollback-v1/source-v1/sound/soc/soc-compress.c', 'sound/soc/soc-compress.c', []),
        'simple-card-utils.c': ('asoc-open-rollback-v1/source-v1/sound/soc/generic/simple-card-utils.c',
            'sound/soc/generic/simple-card-utils.c', ['asoc_simple_hw_params', 'asoc_simple_set_clk_rate',
             'asoc_simple_startup', 'asoc_simple_shutdown']),
        'rk817_codec.c': ('codec-image-v4-v1/source-v1/rk817_codec.c', 'sound/soc/codecs/rk817_codec.c',
            ['rk817_set_dai_sysclk', 'rk817_hw_params', 'rk817_restart_dac_digital_clk_and_apll',
             'rk817_restart_adc_digital_clk_and_apll', 'rk817_codec_shutdown', 'rk817_set_dai_fmt',
             'rk817_codec_power_up', 'rk817_codec_power_down', 'rk817_playback_path_put', 'rk817_capture_path_put',
             'rk817_suspend', 'rk817_resume']),
        'rockchip_i2s_tdm.c': ('cpu-lifecycle-v12/source/sound/soc/rockchip/rockchip_i2s_tdm.c',
            'sound/soc/rockchip/rockchip_i2s_tdm.c', ['i2s_checked_hw_params', 'i2s_checked_params_dirty',
             'i2s_checked_params_trcm', 'rockchip_i2s_tdm_set_mclk', 'rockchip_i2s_tdm_set_sysclk',
             'i2s_checked_gate_locked']),
    }
    functions = {}
    for leaf, (rel, sdkrel, names) in groups.items():
        path = AUDIO / rel
        meta = metadata(path)
        if sdkrel in declared and meta['sha256'] != declared[sdkrel]['sha256']:
            raise ValueError('Latest private source changed')
        sdk = SOURCE / sdkrel
        current = metadata(sdk)
        expected = inventory[sdkrel]
        git_mode = '100755' if current['mode'] & 0o111 else '100644'
        if current != meta or expected != {'bytes': current['bytes'], 'mode': git_mode, 'sha256': current['sha256']}:
            raise ValueError('Actual integrated source or Image source binding differs: ' + sdkrel)
        dest = out / leaf
        shutil.copy2(path, dest)
        if metadata(dest) != meta:
            raise ValueError('Snapshot changed')
        files[str(path.relative_to(ROOT))] = {**meta, 'snapshot': str(dest.relative_to(HERE))}
        bindings[sdkrel] = {'actual_SOURCE': str(sdk.relative_to(ROOT)), 'ordinary': current,
            'Image_inventory_entry': expected, 'snapshot_sha256': meta['sha256']}
        functions[leaf] = identify_functions(path, names)
    sdk_groups = {
        'soc-dai.c': ('sound/soc/soc-dai.c', ['snd_soc_dai_hw_params', 'snd_soc_dai_hw_free', 'snd_soc_dai_set_sysclk', 'snd_soc_dai_active']),
        'soc-link.c': ('sound/soc/soc-link.c', ['snd_soc_link_hw_params', 'snd_soc_link_hw_free', 'snd_soc_link_be_hw_params_fixup']),
        'simple-card.c': ('sound/soc/generic/simple-card.c', []),
        'soc-generic-dmaengine-pcm.c': ('sound/soc/soc-generic-dmaengine-pcm.c', ['dmaengine_pcm_hw_params', 'snd_dmaengine_pcm_prepare_slave_config']),
        'soc.h': ('include/sound/soc.h', []),
        'soc-dai.h': ('include/sound/soc-dai.h', []),
        'simple_card_utils.h': ('include/sound/simple_card_utils.h', []),
        'rk817_codec.h': ('sound/soc/codecs/rk817_codec.h', []),
    }
    for leaf, (sdkrel, names) in sdk_groups.items():
        path = SOURCE / sdkrel
        meta = metadata(path)
        expected = inventory[sdkrel]
        git_mode = '100755' if meta['mode'] & 0o111 else '100644'
        if expected != {'bytes': meta['bytes'], 'mode': git_mode, 'sha256': meta['sha256']}:
            raise ValueError('Image source entry changed')
        dest = out / leaf
        shutil.copy2(path, dest)
        if metadata(dest) != meta:
            raise ValueError('Snapshot differs')
        files[str(path.relative_to(ROOT))] = {**meta, 'snapshot': str(dest.relative_to(HERE))}
        bindings[sdkrel] = {'actual_SOURCE': str(path.relative_to(ROOT)), 'ordinary': meta, 'Image_inventory_entry': expected}
        functions[leaf] = identify_functions(path, names)
    references = {}
    for rel in ['build/full-duplex-review-v1/README.md', 'build/full-duplex-review-v1/input-manifest.json',
        'asoc-open-rollback-v1/source-manifest-v1.json', 'asoc-open-rollback-v1/model-green-v2/input-manifest.json',
        'asoc-open-rollback-v1/model-green-v2/test-caller-chain.c', 'asoc-open-rollback-v1/model-green-v2/test-params-shim.h',
        'asoc-open-rollback-v1/model-green-v2/source_utils.py', 'asoc-open-rollback-v1/model-green-v2/unit.c',
        'asoc-open-rollback-v1/run-model.py', 'build/integration-v4/manifest.json',
        'build/integration-v4/integrated-source-inventory.json']:
        path = AUDIO / rel
        references[str(path.relative_to(ROOT))] = metadata(path)
    result = {'status': 'DESIGN_SOURCE_IDENTITIES_ONLY_NOT_MODEL_OR_BUILD', 'inputs': files,
        'source_to_Image_inventory': bindings, 'functions': functions, 'reference_inputs_not_copied': references,
        'function_body_identity_only_not_executed': True, 'model_executed': False, 'build_executed': False,
        'board_tested': False, 'duplex_START_authorized': False, 'tool_sha256': sha(Path(__file__))}
    (HERE / 'input-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'ordinary_snapshots': len(files), 'identified_functions': sum(map(len, functions.values())),
        'references': len(references), 'manifest_sha256': sha(HERE / 'input-manifest.json')}))


if __name__ == '__main__':
    main()
