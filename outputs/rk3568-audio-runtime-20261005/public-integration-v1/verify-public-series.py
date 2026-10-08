#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fresh 14-patch SDK replay, actual source identity and one AArch64 object."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME = ROOT / 'outputs/rk3568-audio-runtime-20261005'
SDK = ROOT / 'third_party/linux-rk3588'
ACTUAL = ROOT / '.deps/kernel-source/aiot-3568pq-audio-v3'
ABI = ROOT / '.deps/kernel/aiot-3568pq-audio-v3'
PUBLIC = ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches'
PIN = '9f9e9d18574d0914c0d192a90c3babfe1fd63c95'
CPU = 'sound/soc/rockchip/rockchip_i2s_tdm.c'
CPU_SHA = '7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141'
IMAGE_SHA = '965acb13577032b2f0a44f13508b6a97947398e223a6eab6d04f86d9c7d381fe'
IMAGE_MANIFEST_SHA = 'fcdc399661938b55a95b3559fbaf6d919df141f037d3ce7dc69e2b019b18ace1'
COPY_DIRS = ['include', 'arch/arm64/include', 'scripts']
COPY_FILES = ['.config', 'Module.symvers', 'vmlinux.symvers', 'Makefile']

prepare_spec = importlib.util.spec_from_file_location('public_prepare', HERE / 'prepare-patches.py')
prepare_module = importlib.util.module_from_spec(prepare_spec)
prepare_spec.loader.exec_module(prepare_module)
expected_patches = prepare_module.expected_patches


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected ordinary input: ' + str(path))
    return sha(path.read_bytes())


def save(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def git(directory, *arguments):
    return subprocess.check_output(['git', '-C', str(directory), *arguments])


def run(out, label, argv, timeout=180):
    result = subprocess.run(argv, capture_output=True, timeout=timeout)
    (out / (label + '.stdout')).write_bytes(result.stdout)
    (out / (label + '.stderr')).write_bytes(result.stderr)
    save(out / (label + '.command.json'), {'argv': argv, 'exit': result.returncode})
    if result.returncode:
        raise RuntimeError(label + ' failed: ' + result.stderr.decode(errors='replace'))
    return result


def tracked_inventory(directory):
    """All Git tracked bytes, plus live executable/symlink modes; no .git data."""
    result = {}
    entries = git(directory, 'ls-files', '--stage', '-z').split(b'\0')
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, blob, stage = metadata.split()
        if stage != b'0' or mode not in [b'100644', b'100755', b'120000']:
            raise ValueError('Unexpected source index entry: ' + os.fsdecode(name))
        relative = os.fsdecode(name)
        path = directory / relative
        actual_mode = path.lstat().st_mode
        if mode == b'120000':
            if not stat.S_ISLNK(actual_mode):
                raise ValueError('Tracked symlink changed type')
            data = os.fsencode(os.readlink(path))
            live_mode = '120000'
        else:
            if not stat.S_ISREG(actual_mode):
                raise ValueError('Tracked source changed type')
            data = path.read_bytes()
            live_mode = '100755' if actual_mode & stat.S_IXUSR else '100644'
        result[relative] = {'sha256': sha(data), 'bytes': len(data), 'mode': live_mode}
    return result


def abi_inventory(directory):
    result = {}
    for relative in COPY_DIRS + COPY_FILES:
        path = directory / relative
        if path.is_symlink() or not path.exists():
            raise ValueError('ABI input missing/symlink')
        for member in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if member.is_symlink():
                raise ValueError('ABI symlink')
            if member.is_file():
                result[member.relative_to(directory).as_posix()] = file_sha(member)
    return result


def frozen_inputs():
    result = {}
    expected_inventories = {
        'cpu-lifecycle-v11': '7d36c8f14369b6b88ffbbc700a9b35c3d30a23d98eadd9cee88affa658a20a88',
        'cpu-lifecycle-v12': '46b7d7851a135de4943303ea62ae3c6abe5e207d3f1390f4a4c5b333f7b5e8c8',
        'cpu-lifecycle-v12/post-freeze-review-v1': 'b0f9e8516ff927a4025c459dc15288ec294db301c6f313dc27bf8594f0c954ed',
    }
    for relative in ['cpu-lifecycle-v11', 'cpu-lifecycle-v12',
                     'cpu-lifecycle-v12/post-freeze-review-v1']:
        directory = RUNTIME / relative
        path = directory / 'frozen-output-manifest.json'
        if file_sha(path) != expected_inventories[relative]:
            raise ValueError('Prior frozen inventory changed: ' + relative)
        manifest = json.loads(path.read_text())
        entries = dict(manifest['files_sha256'])
        entries[path.name] = file_sha(path)
        entries['SHA256SUMS'] = file_sha(directory / 'SHA256SUMS')
        for name, digest in entries.items():
            if file_sha(directory / name) != digest:
                raise ValueError('Prior frozen file changed: ' + relative + '/' + name)
        result[relative] = {'inventory_sha256': file_sha(path),
                            'verified_files': len(entries), 'files_sha256': entries}
    return result


def external_inputs(image_manifest):
    names = list(image_manifest['patches_sha256'])
    names += ['outputs/rk3568-audio-runtime-20261005/build/integration-v3/Image',
              'outputs/rk3568-audio-runtime-20261005/build/integration-v3/manifest.json',
              'outputs/rk3568-audio-runtime-20261005/build/review-gate-v4.json',
              'outputs/rk3568-audio-runtime-20261005/REVIEW-CPU-v12-20261006.md',
              'outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v12/source_utils.py']
    names += ['outputs/rk3568-audio-runtime-20261005/build/root-v12-' + name + '-v1/result.json'
              for name in ['red', 'format', 'sysclk', 'params']]
    raw = ['pre-playback', 'playback', 'post-playback', 'pre-capture', 'capture',
           'post-capture', 'card-unbound-guard', 'cpu-unbound-guard']
    names += ['outputs/rk3568-pid1-20261005/private/audio-v4-' + name + '-20261006-v1.raw.txt'
              for name in raw]
    names += [path.relative_to(ROOT).as_posix() for path in sorted(PUBLIC.glob('*.patch'))]
    return {name: file_sha(ROOT / name) for name in sorted(set(names))}


def build_object(out, replay, before_abi):
    work = out / 'work/kernel-abi'
    work.mkdir()
    for relative in COPY_DIRS:
        shutil.copytree(ABI / relative, work / relative)
    for relative in COPY_FILES:
        shutil.copy2(ABI / relative, work / relative)
    if abi_inventory(work) != before_abi:
        raise ValueError('Fresh shadow ABI copy mismatch')
    config = (work / '.config').read_text().splitlines()
    required = ['CONFIG_SND_SOC_ROCKCHIP_I2S_TDM=y', 'CONFIG_SND_DMAENGINE_PCM=y',
                'CONFIG_SND_SOC_GENERIC_DMAENGINE_PCM=y', 'CONFIG_PL330_DMA=y',
                'CONFIG_PM=y', 'CONFIG_PM_SLEEP=y', 'CONFIG_NO_GKI=y',
                '# CONFIG_SND_SOC_ROCKCHIP_I2S_TDM_MULTI_LANES is not set']
    if any(item not in config for item in required):
        raise ValueError('Actual integration config differs')
    compiler = subprocess.check_output(['aarch64-linux-gnu-gcc', '--version'], text=True).splitlines()[0]
    if compiler != 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0':
        raise ValueError('Compiler differs from actual Image')
    objects = out / 'kbuild/objects'
    objects.mkdir(parents=True)
    shutil.copy2(replay / CPU, objects / 'rockchip_i2s_tdm.c')
    headers = {}
    for name in ['rockchip_i2s_tdm.h', 'rockchip_dlp.h']:
        source = replay / 'sound/soc/rockchip' / name
        shutil.copy2(source, objects / name)
        headers[name] = file_sha(source)
    (objects / 'Makefile').write_text('# Fresh object-only SDK validation.\nobj-m += rockchip_i2s_tdm.o\n')
    paths = [replay / 'arch/arm64/include', work / 'arch/arm64/include/generated',
             replay / 'include', work / 'include', replay / 'arch/arm64/include/uapi',
             work / 'arch/arm64/include/generated/uapi', replay / 'include/uapi',
             work / 'include/generated/uapi']
    includes = ' '.join('-I' + str(path) for path in paths)
    includes += ' -include ' + str(replay / 'include/linux/kconfig.h')
    argv = ['make', '-C', str(work), 'M=' + str(objects), 'ARCH=arm64',
            'CROSS_COMPILE=aarch64-linux-gnu-', 'LINUXINCLUDE=' + includes,
            'V=1', '-j2', 'rockchip_i2s_tdm.o']
    run(out / 'kbuild', 'build', argv)
    obj = objects / 'rockchip_i2s_tdm.o'
    data = obj.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<HH', data, 16) != (1, 183):
        raise ValueError('Object must be ELF64 LE AArch64 ET_REL')
    run(out / 'kbuild', 'readelf', ['aarch64-linux-gnu-readelf', '-h', '-S', str(obj)])
    return {'exit': 0, 'source_sha256': file_sha(objects / 'rockchip_i2s_tdm.c'),
            'object_bytes': len(data), 'object_sha256': file_sha(obj),
            'object_cmd_sha256': file_sha(objects / '.rockchip_i2s_tdm.o.cmd'),
            'compiler': compiler, 'argv': argv, 'required_config': required,
            'headers_sha256': headers, 'actual_v3_ABI_files': len(before_abi),
            'object_only': True, 'new_Image_built': False, 'hardware_operated': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=HERE / 'verification-v1')
    args = parser.parse_args()
    out = args.out.absolute()
    if out.parent.resolve() != HERE or out.exists() or out.is_symlink():
        raise ValueError('Output must be a fresh immediate child of public-integration-v1')
    # All caller inputs are read before creating any replay/build directory.
    image_path = RUNTIME / 'build/integration-v3/manifest.json'
    if file_sha(image_path) != IMAGE_MANIFEST_SHA:
        raise ValueError('Actual Image manifest changed')
    manifest = json.loads(image_path.read_text())
    if manifest['source_commit'] != PIN or manifest['cpu_source_sha256'] != CPU_SHA or \
            manifest['image_sha256'] != IMAGE_SHA or manifest['battery_algorithm_enabled'] is not False:
        raise ValueError('Actual Image identity/profile mismatch')
    patches = sorted(PUBLIC.glob('*.patch'))
    if len(patches) != 14 or [int(p.name[:4]) for p in patches] != list(range(1, 15)):
        raise ValueError('Expected exact public 0001 through 0014 chain')
    original_chain = list(manifest['patches_sha256'].items())
    if len(original_chain) != 14:
        raise ValueError('Actual Image patch chain changed')
    for patch, (name, digest) in zip(patches[:12], original_chain[:12]):
        if file_sha(patch) != digest or patch.read_bytes() != (ROOT / name).read_bytes():
            raise ValueError('Prior public/private patch mismatch')
    for name, data in expected_patches().items():
        if (PUBLIC / name).read_bytes() != data:
            raise ValueError('New public patch differs from exact wrapper')
    if file_sha(RUNTIME / 'build/integration-v3/Image') != IMAGE_SHA:
        raise ValueError('Actual Image bytes differ')
    for directory in [SDK, ACTUAL]:
        if git(directory, 'rev-parse', 'HEAD').decode().strip() != PIN:
            raise ValueError('Wrong SDK pin')
        if git(directory, 'diff', '--cached'):
            raise ValueError('Unexpected staged SDK edits')
    if git(SDK, 'status', '--porcelain=v1', '--untracked-files=all'):
        raise ValueError('Original SDK is not clean')
    before_sdk = tracked_inventory(SDK)
    before_actual = tracked_inventory(ACTUAL)
    before_abi = abi_inventory(ABI)
    before_frozen = frozen_inputs()
    before_external = external_inputs(manifest)
    if file_sha(ACTUAL / CPU) != CPU_SHA or file_sha(ABI / '.config') != manifest['config_sha256']:
        raise ValueError('Actual source/ABI differ from built Image')
    out.mkdir()
    work = out / 'work'
    work.mkdir()
    replay = work / 'sdk-replay'
    run(out, 'clone', ['git', '-c', 'core.autocrlf=false', 'clone', '--shared',
                       '--no-checkout', str(SDK), str(replay)])
    run(out, 'checkout', ['git', '-C', str(replay), '-c', 'core.hooksPath=/dev/null',
                          '-c', 'core.autocrlf=false', 'checkout', '--detach', PIN])
    if tracked_inventory(replay) != before_sdk:
        raise ValueError('Fresh pristine SDK copy differs')
    (out / 'patches').mkdir()
    sequence = []
    expected_cpu = {12: 'cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59',
                    13: '87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c',
                    14: CPU_SHA}
    for index, path in enumerate(patches, 1):
        saved = out / 'patches' / path.name
        shutil.copy2(path, saved)
        prefix = 'patch-' + path.name[:4]
        run(out, prefix + '-check', ['git', '-C', str(replay), 'apply', '--check', str(saved)])
        run(out, prefix + '-apply', ['git', '-C', str(replay), 'apply', str(saved)])
        cpu_sha = file_sha(replay / CPU)
        if index in expected_cpu and cpu_sha != expected_cpu[index]:
            raise ValueError('Unexpected intermediate CPU identity')
        sequence.append({'number': index, 'public_patch': path.relative_to(ROOT).as_posix(),
                         'patch_sha256': file_sha(saved), 'CPU_after_sha256': cpu_sha,
                         'check_exit': 0, 'apply_exit': 0})
    replay_inventory = tracked_inventory(replay)
    if replay_inventory != before_actual:
        raise ValueError('Complete tracked SDK bytes/modes differ from actual Image source')
    actual_diff = git(ACTUAL, 'diff', '--binary', '--no-ext-diff', 'HEAD')
    if git(replay, 'diff', '--binary', '--no-ext-diff', 'HEAD') != actual_diff:
        raise ValueError('Full actual/public source Git diff differs')
    actual_status = git(ACTUAL, 'status', '--porcelain=v1', '--untracked-files=all')
    if git(replay, 'status', '--porcelain=v1', '--untracked-files=all') != actual_status:
        raise ValueError('Actual/public source status differs')
    changed = [name for name in before_sdk if before_sdk[name] != before_actual[name]]
    (out / 'source').mkdir()
    shutil.copy2(replay / CPU, out / 'source/rockchip_i2s_tdm.c')
    (out / 'source/complete-source.diff').write_bytes(actual_diff)
    (out / 'source/source-status.txt').write_bytes(actual_status)
    save(out / 'source/tracked-source-inventory.json', replay_inventory)
    save(out / 'source/actual-v3-ABI-inventory.json', before_abi)
    spec = importlib.util.spec_from_file_location('frozen_source_utils', RUNTIME / 'cpu-lifecycle-v12/source_utils.py')
    functions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(functions)
    names = ['rockchip_i2s_tdm_set_sysclk', 'i2s_checked_hw_params',
             'i2s_checked_runtime_suspend', 'i2s_checked_set_fmt']
    extracted = {name: functions.function((replay / CPU).read_text(), name) for name in names}
    for name, text in extracted.items():
        if text != functions.function((ACTUAL / CPU).read_text(), name):
            raise ValueError('Actual/public function differs: ' + name)
        (out / 'source' / (name + '.c')).write_text(text + '\n')
    build = build_object(out, replay, before_abi)
    save(out / 'kbuild/result.json', build)
    if tracked_inventory(SDK) != before_sdk or tracked_inventory(ACTUAL) != before_actual or \
            abi_inventory(ABI) != before_abi or frozen_inputs() != before_frozen or \
            external_inputs(manifest) != before_external:
        raise ValueError('Protected original SDK/source/ABI/frozen inputs changed')
    save(out / 'protected-frozen-inputs.json', before_frozen)
    save(out / 'external-inputs.json', before_external)
    receipt = {'exit': 0, 'pinned_SDK_commit': PIN, 'public_patch_sequence': sequence,
               'tracked_source_files_verified': len(replay_inventory),
               'complete_tracked_source_bytes_and_modes_equal_actual_v3': True,
               'source_changes': changed, 'source_changed_files': len(changed),
               'CPU_full_source_sha256': CPU_SHA,
               'CPU_functions_sha256': {name: sha(text.encode()) for name, text in extracted.items()},
               'Image_sha256': IMAGE_SHA, 'Image_manifest_sha256': IMAGE_MANIFEST_SHA,
               'actual_v3_ABI_files_verified': len(before_abi), 'new_object': build,
               'protected_inputs_unchanged': True,
               'inherited_models': 'Root already freshly executed real v11 red 4/5 and v12 format90/sysclk48/params140 in three environments; this wrapper conversion reruns no behavior models.',
               'hardware_operated': False, 'new_Image_built': False,
               'full_duplex_validated': False, 'physical_audio_validated': False,
               'formal_flash_validated': False,
               'scope': 'Fresh public source replay and object build, with hash-bound existing root model/board evidence. Git metadata and disposable work/source/ABI trees are outside the later thin evidence freeze.'}
    save(out / 'receipt.json', receipt)
    print(json.dumps({key: receipt[key] for key in ['exit', 'tracked_source_files_verified',
                                                   'source_changed_files', 'CPU_full_source_sha256',
                                                   'actual_v3_ABI_files_verified', 'new_object']}, indent=2))


if __name__ == '__main__':
    main()
