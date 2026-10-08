#!/usr/bin/env python3
"""Bind the reviewed CPU shutdown correction to fresh private build tools."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CPU = HERE / 'cpu-lifecycle-v11'
OLD_GATE_SHA = 'cbad7ecff36098d4dbc0d49db3191f966bcf4107595e733671be0330e20781af'
CPU_INVENTORY_SHA = '7d36c8f14369b6b88ffbbc700a9b35c3d30a23d98eadd9cee88affa658a20a88'
CPU_SOURCE_SHA = '87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c'
CPU_DELTA_SHA = 'dd31e7208c71bdc7dac8b41c8d82f9e2702f77c743a80214044d8b28e5422437'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Unique versioning anchor required: ' + old[:100])
    return text.replace(old, new, 1)


def fresh_write(path, text):
    if path.exists() or path.is_symlink():
        raise ValueError('Fresh output required: ' + str(path))
    path.write_bytes(text.encode())


def main():
    old_gate = HERE / 'build/review-gate-v2.json'
    if sha(old_gate) != OLD_GATE_SHA:
        raise ValueError('Previous integration gate changed')
    previous = json.loads(old_gate.read_text())
    if previous['accepted_for_offline_integration'] is not True:
        raise ValueError('Previous series not accepted')
    bound = dict(previous['files_sha256'])
    inventory = CPU / 'frozen-output-manifest.json'
    if sha(inventory) != CPU_INVENTORY_SHA:
        raise ValueError('CPU v11 inventory changed')
    frozen = json.loads(inventory.read_text())['files_sha256']
    if len(frozen) != 2249:
        raise ValueError('Incomplete CPU v11 freeze')
    for name, expected in frozen.items():
        bound[(CPU / name).relative_to(ROOT).as_posix()] = expected
    rerun = HERE / 'build/cpu-v11-root-reexecution-v1/result.json'
    result = json.loads(rerun.read_text())
    if not (result['passed'] and result['fresh_compilation'] and
            result['inventory_files_checked'] == 2249 and not result['board_tested']):
        raise ValueError('Root fresh compilation/runtime required')
    for name, expected in result['evidence_sha256'].items():
        bound[(rerun.parent / name).relative_to(ROOT).as_posix()] = expected
    if sha(CPU / 'source/delta-v10-v11.patch') != CPU_DELTA_SHA:
        raise ValueError('Reviewed delta changed')

    builder = (HERE / 'build-audio-image.py').read_text()
    builder = builder.replace('aiot-3568pq-audio-v1', 'aiot-3568pq-audio-v2')
    builder = replace_once(builder, "output = HERE / 'build/integration-v1'",
                           "output = HERE / 'build/integration-v2'")
    builder = replace_once(builder,
                           "CPU_SHA = 'cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59'",
                           "CPU_SHA = '" + CPU_SOURCE_SHA + "'")
    builder = replace_once(builder, '    patches += [c3_patch, cpu_patch]',
                           "    cpu_delta = HERE / 'cpu-lifecycle-v11/source/delta-v10-v11.patch'\n"
                           "    if gate.get('cpu_v11_independent_review_completed') is not True:\n"
                           "        raise ValueError('CPU v11 independent review required')\n"
                           "    if bound.get(cpu_delta.relative_to(ROOT).as_posix()) != '" + CPU_DELTA_SHA + "':\n"
                           "        raise ValueError('Reviewed CPU v11 delta required')\n"
                           "    patches += [c3_patch, cpu_patch, cpu_delta]")
    builder = replace_once(builder, "'c3_manifest_sha256': sha(manifest_path), 'cpu_manifest_sha256': CPU_MANIFEST_SHA,",
                           "'c3_manifest_sha256': sha(manifest_path), 'cpu_v10_manifest_sha256': CPU_MANIFEST_SHA,\n"
                           "              'cpu_source_sha256': CPU_SHA, 'cpu_v11_inventory_sha256': '" + CPU_INVENTORY_SHA + "',\n"
                           "              'battery_algorithm_enabled': False,")
    builder_path = HERE / 'build-audio-image-v2.py'
    fresh_write(builder_path, builder)

    codec = (HERE / 'build-integrated-codec.py').read_text()
    codec = codec.replace('aiot-3568pq-audio-v1', 'aiot-3568pq-audio-v2')
    codec = replace_once(codec, "IMAGE = HERE / 'build/integration-v1'",
                         "IMAGE = HERE / 'build/integration-v2'")
    codec = replace_once(codec, "OUT = HERE / 'build/integrated-codec-v1'",
                         "OUT = HERE / 'build/integrated-codec-v2'")
    codec_path = HERE / 'build-integrated-codec-v2.py'
    fresh_write(codec_path, codec)

    for path in [old_gate, inventory, CPU / 'SHA256SUMS', rerun,
                 HERE / 'recheck-cpu-v11.py', HERE / 'REVIEW-CPU-v11-20261006.md',
                 HERE / 'prepare-audio-v2-source.py', HERE / 'build/source-preparation-v2/result.json',
                 builder_path, codec_path, Path(__file__)]:
        bound[path.relative_to(ROOT).as_posix()] = sha(path)
    for name, expected in bound.items():
        path = ROOT / name
        if path.is_symlink() or sha(path) != expected:
            raise ValueError('Reviewed input changed: ' + name)
    gate = {
        'accepted_for_offline_integration': True,
        'c3_manifest': previous['c3_manifest'],
        'files_sha256': bound,
        'independent_review_completed': True,
        'cpu_v11_independent_review_completed': True,
        'review_mode': 'Independent read-only production/caller review and root fresh 4 red, 48 shutdown, 140 params in three environments',
        'supersedes': 'review-gate-v2.json',
        'new_patch_count': 13,
        'full_image_built': False,
        'codec_abi_verified': False,
        'board_start_allowed': False,
        'formal_flash_ready': False,
        'hardware_operated': False,
        'battery_algorithm_enabled': False,
        'battery_parameters': 'Unknown; user will supply later. No guessed calibration.'
    }
    output = HERE / 'build/review-gate-v3.json'
    fresh_write(output, json.dumps(gate, indent=2) + '\n')
    print(json.dumps({'gate_sha256': sha(output), 'bound_files': len(bound),
                      'builder_sha256': sha(builder_path), 'codec_builder_sha256': sha(codec_path)}))


if __name__ == '__main__':
    main()
