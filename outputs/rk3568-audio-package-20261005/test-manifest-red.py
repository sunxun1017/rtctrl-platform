#!/usr/bin/env python3
"""Rehash a complete fixture inventory to expose missing manifest semantic checks."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--fixture', required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('audio_manifest_red', HERE / 'audio-package.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    output = core.fresh_directory(args.out)
    fixture = Path(args.fixture).absolute()
    original = core.unique_json(core.read_ordinary(fixture / 'manifest.json'))
    image = core.read_ordinary(fixture / 'components/kernel')
    inputs = {'kernel': image, **original['image_input']}
    copied = output / 'mutation-candidate'
    shutil.copytree(fixture, copied)
    receipt = core.unique_json(core.read_ordinary(copied / 'receipt.json'))
    cases = []
    mutations = {
        'reject-false-board-tested-claim': {'board_tested': True},
        'reject-old-RCU-check-as-new-Image-identity': {'native_pid1_old_rcu_image_check_is_new_image_identity': True},
        'reject-wrong-rootfs-board-path': {'rootfs_board_path': '/cache/other-rootfs'},
        'reject-flash-ready-claim': {'formal_flash_ready': True},
    }
    for name, patch in mutations.items():
        mutant = {**original, **patch}
        data = core.json_bytes(mutant)
        (copied / 'manifest.json').write_bytes(data)
        receipt['files']['manifest.json'] = core.metadata(data)
        (copied / 'receipt.json').write_bytes(core.json_bytes(receipt))
        try:
            core.audit_directory(copied, inputs)
        except ValueError as error:
            cases.append({'name': name, 'passed': True, 'reason': str(error)})
        else:
            cases.append({'name': name, 'passed': False, 'reason': 'Self-consistent inventory accepted false semantic claim'})
    (output / 'result.json').write_bytes(core.json_bytes({'red_expected': True, 'cases': cases}))
    print(json.dumps(cases, indent=2))
    raise SystemExit(0 if all(item['passed'] for item in cases) else 1)


if __name__ == '__main__':
    main()
