#!/usr/bin/env python3
"""Build a reviewed audio series in the prepared private checkout only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ORIGINAL = ROOT / 'third_party/linux-rk3588'
SOURCE = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v1'
BUILD = ROOT / '.deps/kernel/aiot-3568pq-audio-v1'
BOARD = ROOT / 'platforms/rk3568/boards/aiot-3568pq'
COMMIT = '9f9e9d18574d0914c0d192a90c3babfe1fd63c95'
CONFIG_SHA = '1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'
CPU_SHA = 'cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59'
CPU_MANIFEST_SHA = '92344de6c38aeb3353134150ec9bca75fad84dc3d2071e1bbd7d611fd0d73b56'
CPU_PATCH_SHA = 'ec857605a70abccce88ac71c1e5070b866fb245717ad90ae0db2af26fc9aa495'
CODEC_SHA = '72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64'
CPU = ROOT / 'outputs/rk3568-i2s-lifecycle-20261005'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def original_lock():
    if git(ORIGINAL, 'rev-parse', 'HEAD') != COMMIT or git(ORIGINAL, 'status', '--porcelain'):
        raise ValueError('Original source changed')


def ordinary(relative):
    path = ROOT / relative
    if not path.resolve().is_relative_to(ROOT) or not path.is_file():
        raise ValueError('Repository file required: ' + str(relative))
    for parent in [path, *path.parents]:
        if parent == ROOT:
            break
        if parent.is_symlink():
            raise ValueError('Symlink input: ' + str(relative))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-gate', required=True)
    args = parser.parse_args()
    original_lock()
    gate_path = ordinary(args.review_gate)
    gate = json.loads(gate_path.read_text())
    if gate.get('accepted_for_offline_integration') is not True:
        raise ValueError('Completed independent C3 review required')
    bound = {}
    for name, expected in gate['files_sha256'].items():
        path = ordinary(name)
        if sha(path) != expected:
            raise ValueError('Reviewed file changed: ' + name)
        bound[name] = expected
    manifest_path = ordinary(gate['c3_manifest'])
    if str(manifest_path.relative_to(ROOT)) not in bound:
        raise ValueError('C3 manifest not bound by review')
    c3 = json.loads(manifest_path.read_text())
    c3_directory = manifest_path.parent
    c3_patch = c3_directory / 'C3-lifecycle-review.patch'
    if c3['kernel_commit'] != COMMIT or sha(c3_patch) != c3['patch_sha256']:
        raise ValueError('C3 patch differs from reviewed source')
    for name, expected in c3['source_sha256'].items():
        path = ordinary(str((c3_directory / name).relative_to(ROOT)))
        if sha(path) != expected:
            raise ValueError('C3 candidate changed: ' + name)

    if sha(CPU / 'sealed-v3/manifest.json') != CPU_MANIFEST_SHA:
        raise ValueError('CPU freeze changed')
    cpu_patch = CPU / 'driver-source-v10/i2s-lifecycle-pm.patch'
    if sha(cpu_patch) != CPU_PATCH_SHA:
        raise ValueError('CPU patch changed')
    cpu_review = HERE / 'build/i2s-v10-independent-review/inventory.json'
    if sha(cpu_review) != '111c020d389bfcaab0088888bf85b1afc47bc62aeea14b00917e771bb48bfd8d':
        raise ValueError('CPU independent review changed')
    for name, expected in json.loads(cpu_review.read_text())['files_sha256'].items():
        if sha(cpu_review.parent / name) != expected:
            raise ValueError('CPU review evidence changed: ' + name)

    output = HERE / 'build/integration-v1'
    if output.exists() or output.is_symlink():
        raise ValueError('Fresh integration output required')
    if SOURCE.is_symlink() or BUILD.is_symlink() or git(SOURCE, 'rev-parse', 'HEAD') != COMMIT:
        raise ValueError('Prepared independent source required')
    if git(SOURCE, 'status', '--porcelain') or (BUILD / 'arch/arm64/boot/Image').exists():
        raise ValueError('Prepared source/build already used')
    if sha(BUILD / '.config') != CONFIG_SHA:
        raise ValueError('Tested config required')
    output.mkdir(parents=True)
    env = dict(os.environ)
    env['PATH'] = str(ROOT / '.deps/host-tools/bin') + ':' + env['PATH']
    compiler = subprocess.check_output(['aarch64-linux-gnu-gcc', '--version'], text=True, env=env).splitlines()[0]
    if compiler != 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0':
        raise ValueError('Compiler differs from tested Image')

    patches = []
    for number in range(1, 11):
        matches = sorted((BOARD / 'patches').glob(f'{number:04d}-*.patch'))
        if len(matches) != 1:
            raise ValueError('One public patch required for ' + str(number))
        relative = str(matches[0].relative_to(ROOT))
        if bound.get(relative) != sha(matches[0]):
            raise ValueError('Public patch not bound by integration review: ' + relative)
        patches.append(matches[0])
    patches += [c3_patch, cpu_patch]
    applied = {}
    for number, patch in enumerate(patches, 1):
        check = subprocess.run(['git', '-C', str(SOURCE), 'apply', '--check', str(patch)],
                               capture_output=True, text=True)
        (output / f'patch-{number:02d}-check.txt').write_text(check.stdout + check.stderr)
        check.check_returncode()
        subprocess.run(['git', '-C', str(SOURCE), 'apply', str(patch)], check=True)
        applied[str(patch.relative_to(ROOT))] = sha(patch)
    for name, expected in c3['source_sha256'].items():
        if sha(SOURCE / name) != expected:
            raise ValueError('Replayed C3 source differs: ' + name)
    if sha(SOURCE / 'sound/soc/rockchip/rockchip_i2s_tdm.c') != CPU_SHA:
        raise ValueError('Replayed CPU differs')
    if sha(SOURCE / 'sound/soc/codecs/rk817_codec.c') != CODEC_SHA:
        raise ValueError('Replayed codec differs')

    argv = ['make', '-C', str(SOURCE), 'O=' + str(BUILD), 'ARCH=arm64',
            'CROSS_COMPILE=aarch64-linux-gnu-', '-j8', 'Image', 'modules']
    inputs = {'source_commit': COMMIT, 'config_sha256': CONFIG_SHA, 'compiler': compiler,
              'review_gate_sha256': sha(gate_path), 'reviewed_files_sha256': bound,
              'c3_manifest_sha256': sha(manifest_path), 'cpu_manifest_sha256': CPU_MANIFEST_SHA,
              'patches_sha256': applied, 'build_argv': argv, 'builder_sha256': sha(Path(__file__)),
              'board_tested': False, 'deployed': False}
    (output / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    print('REVIEWED_AUDIO_IMAGE_BUILD_STARTED', flush=True)
    with (output / 'build.txt').open('w') as stream:
        result = subprocess.run(argv, env=env, stdout=stream, stderr=subprocess.STDOUT)
    original_lock()
    if result.returncode:
        raise ValueError('Full Image/modules build failed; evidence preserved')
    if sha(BUILD / '.config') != CONFIG_SHA:
        raise ValueError('Build changed configuration')
    for name in ['arch/arm64/boot/Image', '.config', 'vmlinux.symvers', 'Module.symvers']:
        target = 'kernel.config' if name == '.config' else Path(name).name
        shutil.copyfile(BUILD / name, output / target)
    data = (output / 'Image').read_bytes()
    if data[0x38:0x3c] != b'ARM\x64':
        raise ValueError('Invalid ARM64 Image')
    manifest = {**inputs, 'image_sha256': sha(output / 'Image'), 'image_bytes': len(data),
                'image_crc32': f'{zlib.crc32(data):08x}', 'image_memory_bytes': int.from_bytes(data[16:24], 'little'),
                'text_offset': int.from_bytes(data[8:16], 'little'),
                'kernel_release': (BUILD / 'include/config/kernel.release').read_text().strip(),
                'module_symvers_sha256': sha(output / 'Module.symvers'),
                'vmlinux_symvers_sha256': sha(output / 'vmlinux.symvers'),
                'original_clean': True, 'build_exit_code': result.returncode}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({key: manifest[key] for key in ['image_sha256', 'image_bytes', 'image_crc32', 'image_memory_bytes']}), flush=True)


if __name__ == '__main__':
    main()
