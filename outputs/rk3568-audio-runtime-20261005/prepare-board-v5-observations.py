#!/usr/bin/env python3
"""Prepare exact fresh identity/codec/cleanup observations; execute none."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
from types import ModuleType

HERE = Path(__file__).resolve().parent
OUT = HERE / 'build/board-audio-v5'
OLD = HERE / 'build/board-audio-v4'
NOTES_SHA = 'a2008d938402984c29c007a3e2bb229d862776d35ed1bfc3f0246a34650b6436'
NOTES_HEX = '040000001400000003000000474e550051e22386ae723cd9247a05f17f2b8a668c0de9070600000001000000000100004c696e757800000000000000'
GNU_BUILD_ID = '51e22386ae723cd9247a05f17f2b8a668c0de907'
POLICY_SHA = '23431a6b7647531ddd54474c6723a2bb6a77b7d105f2ef2dd6fc9d4f0448775c'
IMAGE_SHA = '48b9958d36e2b4821235520360530faac38c9f2dae072c2a2602dbda7e048595'
BASELINES = {
    'codec-observation.json': 'cf8fd972b2b303b62f963850b753cd8878bf8ac9ab602af853f6bfcd83dfbc21',
    'fresh-fdt-before-boot.json': '032113722151aacc6e333198ad908b4434438b3c6ebbc6b3a247ce332d28cae4',
    'android-return-identity.json': '8028963cd2afa80f61dd493e610f3f5c5a4c3b88634e59b5d7abfa8dd1d074a6',
    'unmount-audio-debug.json': 'c32b8e4a25392ed941dc4477f19c1da4f15a4166c74f42304ce32a2da5247acf',
}
CLEANUP = {
    'unbind-card.json': '34af91afa38b2955e3287be7edbe2dc6d1ed1c3ea5dd2d14bdd80bf908e64f98',
    'unload-codec.json': 'd618be17dcde5004a0e3e80bdecf166875a16609fd3424f7a263eedaf52e72ec',
    'unbind-cpu.json': '3e78820785ecca1c4b221dc08c66f2ff255936608c46f1039cc229f92afcfb59',
    'pre-native-return.json': '3540908d54ccb90909f92373eedaed3156928d10261a6dac3fcb941f6ed134f0',
    'after-playback-observation.json': '5cf316e44d6a64ffc41f1e7eae021de1fcdec70387634c1a150088f87dbcac88',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_policy(path=None):
    path = Path(path) if path is not None else HERE / 'prepare-audio-board-trial-v5.py'
    root = HERE.parents[1]
    require(path.is_relative_to(root) and '..' not in path.parts and stat.S_ISREG(path.lstat().st_mode),
            'Ordinary fixed board policy required')
    ancestor = path.parent
    while True:
        require(stat.S_ISDIR(ancestor.lstat().st_mode), 'Nonordinary policy ancestor')
        if ancestor == root:
            break
        ancestor = ancestor.parent
    payload = path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == POLICY_SHA, 'Reviewed primary policy full SHA changed before execution')
    module = ModuleType('reviewed_board_v5_policy')
    module.__file__ = str(path)
    exec(compile(payload, str(path), 'exec'), module.__dict__)
    return module


def identity_steps(notes):
    require(notes.get('image_sha256') == IMAGE_SHA and notes.get('notes_bytes') == 60 and
            notes.get('notes_sha256') == NOTES_SHA and notes.get('notes_hex') == NOTES_HEX and
            notes.get('gnu_build_id') == GNU_BUILD_ID and notes.get('board_verified') is False,
            'Exact accepted actual new notes required')
    return [
        {'command': 'uname -a', 'wait': 1}, {'command': 'cat /proc/version', 'wait': 1},
        {'command': 'stat -c %s /sys/kernel/notes', 'wait': 1, 'expect': r'(?m)^60\r?$'},
        {'command': 'sha256sum /sys/kernel/notes', 'wait': 1, 'expect': NOTES_SHA + '  /sys/kernel/notes'},
        {'command': 'hexdump -v -e \'1/1 "%02x"\' /sys/kernel/notes', 'wait': 1, 'expect': NOTES_HEX},
        {'command': 'sha256sum /proc/1/exe', 'wait': 1,
         'expect': '249cc1cfd87cbddc8618e81e6b8fd742526de78fd964d4a4b3b59b8a7d76368b  /proc/1/exe'},
        {'command': 'cat /proc/modules', 'wait': 1}, {'command': 'cat /proc/mounts', 'wait': 1},
        {'command': 'stat -c %s /sys/firmware/fdt', 'wait': 1}, {'command': 'sha256sum /sys/firmware/fdt', 'wait': 1},
        {'command': 'cat /proc/cmdline', 'wait': 1}, {'command': 'cat /proc/self/status', 'wait': 1},
    ]


def main():
    policy = load_policy()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-input-manifest-sha256', type=policy.digest, required=True)
    args = parser.parse_args()
    board = policy.read_json(OUT / 'input-manifest.json', args.board_input_manifest_sha256)
    policy.validate_false_flags(board, ['board_tested', 'start_allowed', 'battery_algorithm_enabled',
                                       'usb_peripheral_enabled', 'early_emmc_candidate_included'])
    require(board['image_sha256'] == IMAGE_SHA and board['codec_manifest_sha256'] == policy.CODEC_MANIFEST_SHA and
            board['notes_identity_sha256'] == policy.NOTES_IDENTITY_SHA, 'Prepared board input binding changed')
    notes_path = HERE / 'build/live-image-v4-id/identity.json'
    notes = policy.read_json(notes_path, policy.NOTES_IDENTITY_SHA)
    files = {'live-image-identity-v1.json': identity_steps(notes)}
    for name, expected in BASELINES.items():
        files[name] = policy.read_json(OLD / name, expected)
    codec = json.dumps(files['codec-observation.json'])
    codec = codec.replace('59373c55bac7c0b89c2da52f489c32f90d4dac2b0a85f55aafb87163f1d370af', NOTES_SHA)
    codec = codec.replace('d62205da6efae956ceb8b78059dc90fa405dfef82f94bdb7b8f003a6330ecbf7', policy.RUNTIME_FIXED['snd-soc-rk817.ko'][2])
    codec = codec.replace('AUDIO_V4_IMAGE_AND_GUARD_ID_VERIFIED', 'AUDIO_V5_IMAGE_AND_GUARD_ID_VERIFIED')
    files['codec-observation.json'] = json.loads(codec)
    files['codec-observation.json'].insert(7, {'command':
        'test "$(cat /proc/asound/card1/id)" = rockchiprk809co && test -c /dev/snd/controlC1 && '
        'test -c /dev/snd/pcmC1D0p && test -c /dev/snd/pcmC1D0c && echo AUDIO_V5_CARD1_BOTH_PCM_PRESENT',
        'wait': 1, 'expect': r'(?m)^AUDIO_V5_CARD1_BOTH_PCM_PRESENT\r?$'})
    for name, expected in CLEANUP.items():
        files[name] = policy.read_json(HERE / 'build/live-audio-v4' / name, expected)
    for name, steps in files.items():
        require(not (OUT / name).exists() and not (OUT / name).is_symlink(), 'Fresh observation file required')
        for item in steps:
            policy.step(item['command'], item.get('expect'), item.get('wait', 1))
    for name, steps in files.items():
        with (OUT / name).open('xb') as stream:
            stream.write((json.dumps(steps, indent=2) + '\n').encode('ascii'))
    proof = {'prepared_only': True, 'board_tested': False, 'start_allowed': False,
        'image_identity_sha256': policy.sha(notes_path), 'codec_manifest_sha256': policy.CODEC_MANIFEST_SHA,
        'board_input_manifest_sha256': args.board_input_manifest_sha256, 'tool_sha256': policy.sha(Path(__file__)),
        'board_input_policy_sha256': policy.sha(HERE / 'prepare-audio-board-trial-v5.py'),
        'baseline_input_sha256': {**{'build/board-audio-v4/' + name: value for name, value in BASELINES.items()},
                                  **{'build/live-audio-v4/' + name: value for name, value in CLEANUP.items()}},
        'files_sha256': {name: policy.sha(OUT / name) for name in files},
        'notes_are_build_identity_not_full_live_RAM_Image_SHA': True,
        'normal_native_three_selftests_and_RAM_return_use_existing_root_operator_workflow': True}
    with (OUT / 'observation-preparation.json').open('xb') as stream:
        stream.write((json.dumps(proof, indent=2) + '\n').encode())
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
