#!/usr/bin/env python3
"""Windows-safe syntax, immutable-byte and manifest-shape checks only."""
import ast
import json
from pathlib import Path

import codec_builder as builder


def main():
    out = builder.HERE / 'windows-static-v1'
    builder.fresh(out)
    out.mkdir()
    checks = []
    for name in ['codec_builder.py', 'prepare_inputs.py', 'preflight.py']:
        ast.parse((builder.HERE / name).read_text())
        checks.append({'name': name + '_syntax', 'passed': True, 'sha256': builder.sha(builder.HERE / name)})
    inputs = json.loads((builder.HERE / 'prepared-inputs-v1.json').read_text())
    for name, item in inputs['inputs'].items():
        source = builder.ROOT / item['source']
        snapshot = builder.HERE / item['snapshot']
        builder.require(builder.sha(source) == builder.sha(snapshot) == item['sha256'], 'Static source bytes changed')
        checks.append({'name': name + '_unchanged_bytes', 'passed': True, 'sha256': item['sha256']})
    record = {'build_exit_code': 0, 'kernel_release': builder.RELEASE,
              'config_sha256': builder.CONFIG_SHA, 'codec_source_sha256': builder.CODEC_SHA,
              'source': builder.SOURCE.relative_to(builder.ROOT).as_posix(),
              'build': builder.ABI.relative_to(builder.ROOT).as_posix(),
              'compressed_audio_enabled': False, 'battery_algorithm_enabled': False,
              'duplex_START_gates_relaxed': False}
    for key in ['image_sha256', 'module_symvers_sha256', 'vmlinux_symvers_sha256',
                'integrated_source_inventory_sha256', 'builder_sha256']:
        record[key] = '1' * 64
    builder.validate_record(record)
    checks.append({'name': 'synthetic_record_parser_shape_only', 'passed': True})
    for name, update in [('failed_Image_rejected', {'build_exit_code': 1}),
                         ('old_tree_rejected', {'source': '.deps/kernel-source/aiot-3568pq-audio-v3'})]:
        try:
            builder.validate_record({**record, **update})
        except ValueError as error:
            checks.append({'name': name, 'passed': True, 'actual_rejection': str(error)})
        else:
            raise ValueError('Expected static rejection missing')
    builder.require(len(checks) == 12, 'Static check count changed')
    result = {'checks': checks, 'total': 12, 'passed': 12,
              'static_checker_sha256': builder.sha(Path(__file__)),
              'builder_sha256': builder.sha(builder.HERE / 'codec_builder.py'),
              'module_build_invoked': False, 'actual_Image_or_ABI_verified': False,
              'SDK_link_semantics_tested': False, 'v4_generated_inputs_read': False,
              'scope': 'Windows syntax/frozen bytes/synthetic manifest parser only'}
    builder.write_json(out / 'result.json', result)
    print(json.dumps({'checks': 12, 'passed': 12, 'module_build_invoked': False}))


if __name__ == '__main__':
    main()
