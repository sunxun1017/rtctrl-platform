#!/usr/bin/env python3
"""Publish the accepted exact patches and bind a concrete offline integration gate."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOARD = ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = HERE / 'build/review-gate-v2.json'
    assert not output.exists()
    verified = HERE / 'build/integration-evidence-v1.json'
    evidence = json.loads(verified.read_text())
    assert evidence['passed'] and evidence['counts']['c3_frozen'] == 883
    bound = {name.replace('\\', '/'): expected for name, expected in evidence['files_sha256'].items()}
    for name, expected in bound.items():
        assert sha(ROOT / name) == expected, name
    rerun = HERE / 'build/c3-v8-root-reexecution-v1/result.json'
    result = json.loads(rerun.read_text())
    assert result['passed'] and result['board_tested'] is False
    for name, expected in result['files_sha256'].items():
        assert sha(rerun.parent / name) == expected, name
    assert all(sum(runs[mode]['tests']['passed'] for runs in result['runs'].values()) == 82
               for mode in ['host', 'host-sanitized', 'aarch64'])
    c3_directory = ROOT / 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/source'
    patches = [
        (c3_directory / 'C3-lifecycle-review.patch', BOARD / '0011-pl330-pcm-lifecycle.patch',
         'c2f973b6f96620b1ac307e5fa5e0632f5430a12a7accbb54cc95088c772b519c'),
        (ROOT / 'outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10/i2s-lifecycle-pm.patch',
         BOARD / '0012-i2s-lifecycle.patch', 'ec857605a70abccce88ac71c1e5070b866fb245717ad90ae0db2af26fc9aa495'),
    ]
    for source, target, expected in patches:
        assert target.is_file() and sha(target) == expected and sha(source) == expected, str(target)
    for source, target, expected in patches:
        bound[target.relative_to(ROOT).as_posix()] = expected
    receipt = json.loads((c3_directory.parent / 'receipt.json').read_text())
    for item in receipt['patch_series'][:10]:
        path = BOARD / Path(item['path']).name
        assert sha(path) == item['sha256']
        bound[path.relative_to(ROOT).as_posix()] = item['sha256']
    for path in [verified, rerun, Path(__file__), HERE / 'REVIEW-DMA-C3-v7.md', HERE / 'REVIEW-DMA-C3-v8.md',
                 HERE / 'REVIEW-I2S-v10.md', HERE / 'build-audio-image.py', HERE / 'build-integrated-codec.py',
                 ROOT / 'outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10/i2s-lifecycle-pm.patch',
                 ROOT / 'outputs/rk3568-i2s-lifecycle-20261005/sealed-v3/manifest.json',
                 ROOT / 'outputs/rk3568-audio-20261005/build-codec.py']:
        bound[path.relative_to(ROOT).as_posix()] = sha(path)
    gate = {'accepted_for_offline_integration': True,
            'c3_manifest': (c3_directory / 'manifest.json').relative_to(ROOT).as_posix(),
            'files_sha256': bound, 'independent_review_completed': True,
            'review_mode': 'Independent read-only functional review plus root fresh compilation/runtime of 82 contracts in three environments',
            'full_image_built': False, 'codec_abi_verified': False, 'board_start_allowed': False,
            'physical_stop_proven': False, 'formal_flash_ready': False, 'hardware_operated': False,
            'supersedes': 'review-gate-v1.json',
            'correction': 'Canonical POSIX repository paths in cross-host JSON. Initial build refused before applying patches.'}
    output.write_text(json.dumps(gate, indent=2) + '\n')
    print(json.dumps({'gate_sha256': sha(output), 'bound_files': len(bound), 'public_patches': [x[1].relative_to(ROOT).as_posix() for x in patches]}))


if __name__ == '__main__':
    main()
