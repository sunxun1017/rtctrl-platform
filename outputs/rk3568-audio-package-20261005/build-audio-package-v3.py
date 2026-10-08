#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the reviewed integration-v2 Image as a new RAM-only package."""
import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-gate', required=True, help='Repository relative completed integration review JSON')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    source = Path(__file__).with_name('audio-package-v3.py')
    spec = importlib.util.spec_from_file_location('audio_package', source)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    inputs = core.production_inputs(args.review_gate)
    manifest = core.construct_package(args.out, inputs)
    print(json.dumps({'status': manifest['status'], 'artifacts': manifest['artifacts'],
                      'board_tested': False, 'formal_flash_ready': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit('AUDIO_PACKAGE_BUILD_REJECTED: ' + str(error))
