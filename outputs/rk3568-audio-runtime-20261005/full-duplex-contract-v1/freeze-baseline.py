#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Independently re-read byte-exact inputs/functions/run artifacts, then seal."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    sealed = HERE / 'sealed-v1'
    sealed.mkdir(exist_ok=False)
    model = HERE / 'model-v5'
    manifest = json.loads((model / 'input-manifest.json').read_text())
    runner = json.loads((HERE / 'runs-v4/receipt.json').read_text())
    spec = importlib.util.spec_from_file_location('source_utils', model / 'source_utils.py')
    util = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(util)
    groups = {
        'cpu': 'outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v12/source/sound/soc/rockchip/rockchip_i2s_tdm.c',
        'simple': '.deps/kernel-source/aiot-3568pq-audio-v2/sound/soc/generic/simple-card-utils.c',
        'codec': 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/full-replay/sound/soc/codecs/rk817_codec.c',
        'dai': 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/full-replay/sound/soc/soc-dai.c',
        'component': 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/full-replay/sound/soc/soc-component.c',
        'pcm': 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/full-replay/sound/soc/soc-pcm.c',
        'link': '.deps/kernel-source/aiot-3568pq-audio-v3/sound/soc/soc-link.c',
        'soc-header': '.deps/kernel-source/aiot-3568pq-audio-v3/include/sound/soc.h',
    }
    for path, item in manifest['input_files'].items():
        snapshot = HERE / item['snapshot']
        assert snapshot.resolve().is_relative_to(HERE)
        assert stat.S_ISREG(snapshot.lstat().st_mode)
        assert sha(snapshot.read_bytes()) == item['sha256']
        assert sha((ROOT / path).read_bytes()) == item['sha256']
    for key, item in manifest['production_functions'].items():
        group, name = key.split(':')
        source = (HERE / manifest['input_files'][groups[group]]['snapshot']).read_text()
        body = util.function(source, name)
        extracted = util.function((model / ('actual-' + group + '-functions.c')).read_text(), name)
        assert body == extracted
        assert sha(body.encode()) == item['sha256']
    assert runner['input_manifest_sha256'] == sha((model / 'input-manifest.json').read_bytes())
    for name, digest in runner['model_files_sha256'].items():
        assert sha((model / name).read_bytes()) == digest
    assert sha((HERE / 'runs-v4/runner-snapshot.py').read_bytes()) == runner['runner_sha256']
    for label, run in runner['runs'].items():
        assert run['compile']['exit'] == 0 and run['execution']['exit'] == 1
        assert run['expected_red_reproduced']
        assert run['counts'] == {'contract_total': 25, 'contract_passed': 0, 'boundary_total': 76, 'boundary_passed': 76}
        assert sha((HERE / 'runs-v4' / ('caller-chain-' + label)).read_bytes()) == run['binary_sha256']
        for prefix, record in [(label + '-compile', run['compile']), (label, run['execution'])]:
            for stream in ['stdout', 'stderr']:
                data = (HERE / 'runs-v4' / (prefix + '.' + stream)).read_bytes()
                assert sha(data) == record[stream + '_sha256']
                if stream == 'stderr':
                    assert not data
    old = json.loads((HERE / 'runs-v2/receipt.json').read_text())
    assert sha((HERE / 'baseline-v3-evidence/runner-recovered-exact.py').read_bytes()) == old['runner_sha256']
    assert sha((HERE / 'model-v3/input-manifest.json').read_bytes()) == old['input_manifest_sha256']
    assert sha((HERE / 'runs-v3/input-manifest.json').read_bytes()) == json.loads((HERE / 'runs-v3/receipt.json').read_text())['input_manifest_sha256']
    metadata = {}
    for label, argv in [('host-compiler', ['gcc', '--version']),
                        ('aarch64-compiler', ['aarch64-linux-gnu-gcc', '--version']),
                        ('qemu', [str(ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'), '--version'])]:
        result = subprocess.run(argv, capture_output=True, timeout=10)
        assert result.returncode == 0
        (sealed / (label + '.stdout')).write_bytes(result.stdout)
        (sealed / (label + '.stderr')).write_bytes(result.stderr)
        metadata[label] = {'argv': argv, 'exit': result.returncode, 'stdout_sha256': sha(result.stdout)}
    files = {}
    for path in sorted(HERE.rglob('*')):
        if not path.is_file():
            continue
        assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
        if path.name in ['manifest.json', 'receipt.json'] and path.parent == sealed:
            continue
        data = path.read_bytes()
        files[path.relative_to(HERE).as_posix()] = {'sha256': sha(data), 'size': len(data)}
    inventory = {'schema': 'rk3568-full-duplex-baseline-seal-v1', 'files': files,
                 'ordinary_count': len(files), 'source_changes': False, 'board_tested': False}
    (sealed / 'manifest.json').write_text(json.dumps(inventory, indent=2) + '\n')
    receipt = {'schema': 'rk3568-full-duplex-baseline-receipt-v1',
               'status': 'OFFLINE_EXPECTED_RED_BASELINE_FROZEN',
               'manifest_sha256': sha((sealed / 'manifest.json').read_bytes()),
               'input_count': len(manifest['input_files']), 'production_function_count': len(manifest['production_functions']),
               'source_functions_byte_exact_rechecked': True,
               'runs': runner['runs'], 'metadata': metadata,
               'final_model': 'model-v5', 'final_runs': 'runs-v4',
               'old_real_PM_version_preserved': ['model-v4', 'inputs-v4', 'runs-v3'],
               'old_synthetic_PM_version_preserved': ['model-v3', 'inputs-v3', 'runs-v2'],
               'old_runner_recovered_SHA_matches_actual_old_receipt': True,
               'old_preparation_SHA_not_recorded_and_not_claimed': True,
               'Kbuild_executed': False, 'production_modified': False, 'board_tested': False,
               'full_duplex_adapted': False, 'duplex_START_authorized': False,
               'limitations': ['not complete kernel or hardware', 'platform DMA/codec trigger/module-open helpers are API models',
                  'PM core/CCF/regmap/IRQ scheduling and constraint errno are API models',
                  'synthetic child clocks and unreachable dual-started fixture labelled',
                  'compressed source caller branches read and locked, not executed in this baseline',
                  'voice sibling DAI cache and generic pinctrl in-flight PM window unresolved']}
    (sealed / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    for path, item in files.items():
        assert sha((HERE / path).read_bytes()) == item['sha256']
    print(json.dumps({'files': len(files), 'functions_rechecked': len(manifest['production_functions']),
        'manifest_sha256': sha((sealed / 'manifest.json').read_bytes()),
        'receipt_sha256': sha((sealed / 'receipt.json').read_bytes())}))


if __name__ == '__main__':
    main()
