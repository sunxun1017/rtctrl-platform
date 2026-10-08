#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract private or original sources into a fresh explicit caller-chain model."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'outputs/rk3568-audio-runtime-20261005/full-duplex-contract-v1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['red', 'green'], required=True)
    parser.add_argument('--version', type=int, required=True)
    args = parser.parse_args()
    out = HERE / f'model-{args.mode}-v{args.version}'
    out.mkdir(exist_ok=False)
    old = BASE / 'model-v5'
    spec = importlib.util.spec_from_file_location('source_utils', old / 'source_utils.py')
    util = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(util)
    function, sha = util.function, util.sha
    manifest = json.loads((old / 'input-manifest.json').read_text())
    source_manifest = json.loads((HERE / 'source-manifest-v1.json').read_text())
    for name in ['test-params-shim.h', 'actual-abi.h', 'actual-cpu-types.h', 'asound.h',
                 'rockchip_i2s_tdm.h', 'actual-formats.h', 'actual-iteration-mark-macros.h', 'source_utils.py']:
        shutil.copyfile(old / name, out / name)
    groups = {}
    funcs = {}
    for key in manifest['production_functions']:
        group, name = key.split(':')
        funcs.setdefault(group, []).append(name)
    for group in funcs:
        groups[group] = (old / ('actual-' + group + '-functions.c')).read_text()
    source_paths = {'pcm': 'sound/soc/soc-pcm.c', 'component': 'sound/soc/soc-component.c',
                    'simple': 'sound/soc/generic/simple-card-utils.c', 'compress': 'sound/soc/soc-compress.c'}
    source_receipt = {}
    for group, path in source_paths.items():
        input_path = HERE / ('source-v1/' + path) if args.mode == 'green' else HERE / 'inputs-v1' / Path(path).name
        data = input_path.read_bytes()
        expected = source_manifest['files'][path]['sha256' if args.mode == 'green' else 'original_sha256']
        assert sha(data) == expected
        groups[group] = data.decode()
        (out / (group + '-source-input.c')).write_bytes(data)
        source_receipt[path] = {'sha256': expected, 'source': input_path.relative_to(HERE).as_posix()}
    funcs['component'] += ['snd_soc_component_module_get', 'snd_soc_component_module_put',
                            'snd_soc_component_open', 'snd_soc_component_close']
    funcs['pcm'] += ['soc_pcm_components_open', 'soc_pcm_components_close']
    if args.mode == 'green':
        funcs['pcm'] += ['soc_pcm_clean_locked', 'soc_pcm_clean_post_unlock']
    funcs['compress'] = ['soc_compr_components_open', 'soc_compr_components_free', 'soc_compr_open', 'soc_compr_free']
    header_path = next(p for p in manifest['input_files'] if p.endswith('/include/sound/soc-component.h'))
    header = (BASE / manifest['input_files'][header_path]['snapshot']).read_text()
    groups['component-header'] = header
    funcs['component-header'] = ['snd_soc_component_active']
    macros = (out / 'actual-iteration-mark-macros.h').read_text()
    lines = header.splitlines(True)
    for name in ['snd_soc_component_module_get_when_open', 'snd_soc_component_module_put_when_close']:
        start = next(i for i, line in enumerate(lines) if line.startswith('#define ' + name + '('))
        stop = start
        while lines[stop].rstrip().endswith('\\'):
            stop += 1
        macros += ''.join(lines[start:stop + 1])
    (out / 'actual-iteration-mark-macros.h').write_text(macros)
    shim = (out / 'test-params-shim.h').read_text()
    shim = shim.replace('unsigned int get_calls, noidle_puts, auto_puts; };',
                        'unsigned int get_calls, noidle_puts, auto_puts; struct device_driver *driver; };')
    shim = shim.replace('static int pm_runtime_get_sync(', 'static int model_pm_get_result(struct device *dev);\nstatic int pm_runtime_get_sync(', 1)
    shim = shim.replace('return dev->inject_get_error ? dev->inject_get_error : pm_error;', 'return model_pm_get_result(dev);', 1)
    (out / 'test-params-shim.h').write_text(shim)
    for name in ['model-extra-primitives.h', 'model-glue.h', 'test-caller-chain.c']:
        (out / name).write_bytes((HERE / name).read_bytes())
    prototypes = ''
    bodies = ''
    units = {}
    for group, names in funcs.items():
        extracted = ''
        for name in names:
            if group == 'component-header' and name == 'snd_soc_component_active':
                prefix = 'static inline unsigned int\nsnd_soc_component_active('
                start = groups[group].index(prefix)
                end = groups[group].index('\n}', start) + 2
                body = groups[group][start:end]
            else:
                body = function(groups[group], name)
            prototypes += body[:body.index('{')].strip() + ';\n'
            extracted += body + '\n\n'
            units[group + ':' + name] = sha(body.encode())
        (out / ('actual-' + group + '-functions.c')).write_text(extracted)
        bodies += extracted
    unit = '#define CANDIDATE ' + str(int(args.mode == 'green')) + '\n'
    unit += '#include "test-params-shim.h"\n#include "actual-abi.h"\n#include "actual-cpu-types.h"\n'
    unit += '#include "model-glue.h"\n' + prototypes + '\n' + bodies + '\n#include "test-caller-chain.c"\n'
    (out / 'unit.c').write_text(unit)
    (out / 'prepare-snapshot.py').write_bytes(Path(__file__).read_bytes())
    record = {'mode': args.mode, 'source_files': source_receipt, 'production_functions_sha256': units,
              'baseline_seal_sha256': sha((BASE / 'sealed-v1/receipt.json').read_bytes()),
              'baseline_manifest_sha256': sha((old / 'input-manifest.json').read_bytes()),
              'unit_sha256': sha(unit.encode()), 'fixtures_sha256': {n: sha((out / n).read_bytes())
                  for n in ['model-extra-primitives.h', 'model-glue.h', 'test-caller-chain.c']},
              'CPU_modified': False, 'board_tested': False, 'full_duplex_START_authorized': False,
              'boundaries': ['kernel regmap/CCF/PM scheduling/IRQ and module API are modelled',
                  'component callbacks, codec callbacks and platform DMA are API side-effect models',
                  'actual PCM/compressed callers and module/open/close/PM/startup mark logic executed',
                  'no complete kernel ABI/DAPM/PL330 or hardware proof']}
    (out / 'input-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'model': out.name, 'functions': len(units), 'unit_sha256': record['unit_sha256']}))


if __name__ == '__main__':
    main()
