#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Independently verify a frozen RAM package and all production Image provenance."""
import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-gate', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    source = Path(__file__).with_name('audio-package-v3.py')
    spec = importlib.util.spec_from_file_location('audio_package', source)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    inputs = core.production_inputs(args.review_gate)
    report = core.audit_directory(args.candidate, inputs)
    output = core.fresh_directory(args.out)
    core.write_new(output / 'audit.json', core.json_bytes(report))
    core.write_new(output / 'receipt.json', core.json_bytes({
        'mode': 'PRODUCTION_AUDIO_RAM_OFFLINE_AUDIT_ONLY',
        'auditor_sha256': core.metadata(source.read_bytes())['sha256'],
        'wrapper_sha256': core.metadata(Path(__file__).read_bytes())['sha256'],
        'audit': core.metadata((output / 'audit.json').read_bytes()),
        'image_manifest': inputs['image_manifest'], 'review_gate': inputs['review_gate'],
        'board_tested': False, 'formal_flash_ready': False}))
    print(json.dumps({'status': 'PRODUCTION_AUDIO_RAM_OFFLINE_VERIFIED',
                      'package': report['package'], 'raw_bytes': report['raw_bytes'],
                      'board_tested': False, 'formal_flash_ready': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit('AUDIO_PACKAGE_AUDIT_REJECTED: ' + str(error))
