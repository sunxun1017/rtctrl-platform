#!/usr/bin/env python3
"""Freeze v8 source, strict full replay, complete regression and real Kbuild evidence."""
import importlib.util
import json
import re
import shutil
from pathlib import Path
from source_utils import sha

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / 'third_party/linux-rk3588'
CPU_ROOT = ROOT / 'outputs/rk3568-i2s-lifecycle-20261005'
GREEN = [
    ('pl330-c3-order2-tests-green-v2', 67),
    ('pl330-c3-hw-tests-green-v3', 17),
    ('pl330-debugfs-tests-green-v6', 2),
    ('dma-admission-tests-green-v6', 9),
    ('trigger-cpu-open-tests-green-v1', 47),
    ('dma-pcm-open-tests-green-v1', 21),
    ('core-lifecycle-tests-green-v4', 6),
    ('pl330-ready2-tests-green-v2', 14),
]
RED = ['pl330-ready-tests-red-v1', 'dma-pcm-open-tests-red-v1', 'pl330-ready2-tests-green-v1', 'pl330-c3-order-tests-green-v1', 'pcm-tests-memory-green-v2']


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_sha(path):
    import hashlib
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def main():
    checker = load('freeze_v5_checks', HERE / 'freeze-c3.py')
    checker.gate()
    candidate = HERE / 'driver-source-c3-v8'
    manifest = json.loads((candidate / 'manifest.json').read_text())
    source_map = manifest['source_sha256']
    for name, wanted in source_map.items():
        checker.check_hash(candidate / name, wanted)
    for name, wanted in manifest['generator_sha256'].items():
        checker.check_hash(HERE / name, wanted)
    checker.check_hash(candidate / 'C3-lifecycle-review.patch', manifest['patch_sha256'])
    production_path = HERE / 'production-v10'
    production = checker.verify_production(production_path, source_map, True)
    checker.require(production['candidate_manifest_sha256'] == sha((candidate / 'manifest.json').read_bytes()), 'production manifest mismatch')
    checker.require(len(production['patch_series']) == 12, 'full public + DMA + CPU series incomplete')
    checker.require(len(production['kbuild_commands_sha256']) == 12, 'actual per-object compiler commands missing')
    patches = []
    names = set(source_map)
    for item in production['patch_series']:
        name = item['patch']
        path = production_path / 'patch-inputs' / name
        checker.check_hash(path, item['sha256'])
        data = path.read_bytes()
        names.update(checker.patch_paths(data))
        patches.append((name, data))
        if name.startswith('0011-'):
            checker.require(data == (candidate / 'C3-lifecycle-review.patch').read_bytes(), 'incremental candidate patch differs')
        elif name.startswith('0012-'):
            checker.check_hash(CPU_ROOT / 'driver-source-v10/i2s-lifecycle-pm.patch', item['sha256'])
        else:
            checker.check_hash(ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches' / name, item['sha256'])
    before = {name: (KERNEL / name).read_bytes() for name in names}
    replay = dict(before)
    incremental_before = None
    for index, (name, data) in enumerate(patches):
        if index == 10:
            incremental_before = dict(replay)
            for target, wanted in manifest['before_sha256'].items():
                checker.require(sha(replay[target]) == wanted, 'exact incremental base mismatch')
        replay.update(checker.replay_exact(replay, data))
    checker.require(all(sha(replay[name]) == wanted for name, wanted in production['replay_files_sha256'].items()), 'strict replay differs from actual production replay')
    checker.require(all(sha(replay[name]) == wanted for name, wanted in source_map.items()), 'strict replay candidate source mismatch')
    checker.require(sha(replay[checker.CPU_PATH]) == checker.CPU_SHA, 'strict replay CPU mismatch')
    tampered = dict(incremental_before)
    key = 'drivers/dma/pl330.c'
    tampered[key] = tampered[key].replace(b'#include <linux/dma-mapping.h>', b'#include <linux/bogus.h>', 1)
    checker.require(tampered[key] != incremental_before[key], 'tamper anchor absent')
    rejected = False
    try:
        checker.replay_exact(tampered, (candidate / 'C3-lifecycle-review.patch').read_bytes())
    except ValueError:
        rejected = True
    checker.require(rejected, 'strict context tamper accepted')
    checker.require(sha((candidate / 'C3-lifecycle-review.patch').read_bytes() + b'tamper') != manifest['patch_sha256'], 'patch digest tamper accepted')
    green_results = []
    for name, count in GREEN:
        result = checker.verify_result(HERE / name, source_map, count)
        green_results.append({'directory': name, 'tests_per_environment': count, 'result_sha256': sha((HERE / name / 'result.json').read_bytes()), 'source_sha256': result['source_sha256']})
    checker.gate()
    review = HERE / 'C3-review-v2'
    review.mkdir(exist_ok=False)
    shutil.copytree(candidate, review / 'source')
    shutil.copytree(production_path / 'patch-inputs', review / 'patch-inputs')
    for name, data in before.items():
        dst = review / 'original-inputs' / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    for name, data in replay.items():
        dst = review / 'full-replay' / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    for name, _ in GREEN:
        shutil.copytree(HERE / name, review / 'tests' / name)
    for name in RED:
        shutil.copytree(HERE / name, review / 'red-evidence' / name)
    for name in ['driver-source-c3-v6', 'driver-source-c3-v7']:
        shutil.copytree(HERE / name, review / 'prior-source' / name)
    for directory in ['production-v8', 'production-v9', 'production-v10']:
        src = HERE / directory
        dst = review / ('production' if directory == 'production-v10' else 'prior-production/' + directory)
        result = json.loads((src / 'result.json').read_text())
        for path in src.iterdir():
            if path.is_file():
                copy_file(path, dst / path.name)
        for name in ['.config', 'include/generated/autoconf.h', 'include/config/auto.conf', 'include/config/kernel.release']:
            if (src / 'build' / name).exists():
                copy_file(src / 'build' / name, dst / 'build' / name)
        if directory == 'production-v10':
            for table in ['objects_sha256', 'kbuild_commands_sha256']:
                for name in result[table]:
                    copy_file(src / 'build' / name, dst / 'build' / name)
    for name in ['sound/soc/rockchip/rockchip_i2s_tdm.c', 'manifest.json', 'i2s-lifecycle-pm.patch']:
        copy_file(CPU_ROOT / 'driver-source-v10' / name, review / 'cpu' / name)
    copy_file(CPU_ROOT / 'sealed-v3/manifest.json', review / 'cpu/sealed-v3-manifest.json')
    for path in HERE.iterdir():
        if path.is_file() and (path.suffix in ['.py', '.h', '.c'] or path.name in ['PLAN.md', 'C2-PLAN.md', 'C3-PLAN.md', 'C3-REVIEW.md', 'READONLY-SCOPE.md', '.gitignore']):
            copy_file(path, review / 'generators' / path.name)
    for name in ['finalize-inspect-v2.json', 'finalize-stop-own-c1-v1.json']:
        copy_file(HERE / name, review / 'handoff' / name)
    for directory in ['finalize-tests-v1', 'finalize-tests-v2', 'finalize-production-v1']:
        shutil.copytree(HERE / directory, review / 'handoff' / directory)
    for name in ['platforms/rk3568/linux-5.10.cfg', 'platforms/rk3568/boards/aiot-3568pq/firstboot.cfg', 'platforms/rk3568/boards/aiot-3568pq/firstboot-candidate.json']:
        copy_file(ROOT / name, review / 'production/profile' / name)
    checker.gate()
    external_failures = []
    for name in ['probe-regression-diagnostic-v1.stderr', 'probe-regression-diagnostic-v1.stdout']:
        path = HERE / name
        external_failures.append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': file_sha(path), 'retained_in_place': True})
    files = {str(path.relative_to(review)): file_sha(path) for path in sorted(review.rglob('*')) if path.is_file()}
    receipt = {
        'c3_frozen': True, 'candidate_rejected': False, 'independent_complete_review_pending': True,
        'published': False, 'deployable': False, 'board_tested': False, 'image_built': False,
        'kernel_commit': checker.COMMIT, 'original_kernel_clean_before_and_after': True,
        'candidate': str(candidate), 'candidate_manifest_sha256': sha((candidate / 'manifest.json').read_bytes()),
        'source_sha256': source_map, 'patch_sha256': manifest['patch_sha256'],
        'incremental_patch': 'patch-inputs/0011-pl330-pcm-lifecycle.patch',
        'incremental_base': 'locked original + exact public 0001-0010',
        'patch_series': [{'path': 'patch-inputs/' + name, 'sha256': sha(data)} for name, data in patches],
        'strict_full_series_replay_matches': True, 'exact_context_tamper_rejected': True, 'patch_hash_tamper_rejected': True,
        'public_0011_created': False, 'production_objects_compiled': True, 'production_objects': 12,
        'production_result': 'production/result.json', 'compiler': production['compiler'], 'config_sha256': production['config_sha256'],
        'cpu': production['cpu'], 'tests_per_environment': sum(count for _, count in GREEN),
        'environments': ['host', 'host-sanitized ASan+UBSan with leak checks', 'static AArch64 under QEMU'],
        'green_results': green_results, 'red_results_retained': RED,
        'large_failure_streams_retained': external_failures,
        'scope': 'C1/C2/C3 + accepted CPU v10 software group; DMA IRQ/init/remove, generic held-channel open, allocator quarantine. No physical AXI/PM/MMIO drain conclusion.',
        'readonly_open': manifest['readonly_open_contract'],
        'supported_client_lifetime': 'PCM prtd.operations covers preparation, submit including rejected giveback until operation_end; process quiesce waits operations0 before close/unregister/release. Bare clients must not release last channel reference while tx_submit still runs.',
        'remaining': ['Independent entire C1/C2/C3 + CPU functional review', 'Main task full Image/link and exact external codec module ABI', 'Physical single-direction MMIO/AXI/STOPPED and teardown proof before any board START'],
        'files_sha256': files,
    }
    (review / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(review / 'receipt.json'), 'receipt_sha256': file_sha(review / 'receipt.json'), 'files': len(files), 'tests_per_environment': receipt['tests_per_environment'], 'objects': 12, 'published': False, 'deployable': False}))


if __name__ == '__main__':
    main()
