#!/usr/bin/env python3
"""Snapshot only immutable codec/provenance inputs, without inspecting a running build."""
from pathlib import Path
import json
import shutil
import traceback

import codec_builder as builder

HERE, ROOT = builder.HERE, builder.ROOT
INPUTS = {
    'frozen_codec': ('.deps/kernel-source/aiot-3568pq-audio-v3/sound/soc/codecs/rk817_codec.c',
                     builder.CODEC_SHA, 'source-v1/rk817_codec.c'),
    'frozen_header': ('.deps/kernel-source/aiot-3568pq-audio-v3/sound/soc/codecs/rk817_codec.h',
                      builder.HEADER_SHA, 'source-v1/rk817_codec.h'),
    'original_codec': ('third_party/linux-rk3588/sound/soc/codecs/rk817_codec.c',
                       'c510119eefe8fd82c1e100fde014d9ce30420aa2df9b1b74cf5e83b9e18ea6f3', 'inputs-v1/original-rk817_codec.c'),
    'original_header': ('third_party/linux-rk3588/sound/soc/codecs/rk817_codec.h',
                        builder.HEADER_SHA, 'inputs-v1/original-rk817_codec.h'),
    'reference_builder_v3': ('outputs/rk3568-audio-runtime-20261005/build-integrated-codec-v3.py',
                             '9266fc9c6260d7211abd95148329c1d4ef56407d6090f6f86b74a7c45812ed64', 'inputs-v1/reference-builder-v3.py'),
    'reference_audit': ('outputs/rk3568-audio-20261005/build-codec.py',
                        '33a56678d16f651c40746b2c8e55531166ff7eecd7bd80e4f24bc58a84688fcb', 'inputs-v1/reference-audit.py'),
}


def main():
    output = HERE / 'preparation-v1'
    builder.fresh(output)
    output.mkdir()
    (output / 'preparer-snapshot.py').write_bytes(Path(__file__).read_bytes())
    builder.write_json(output / 'invocation.json', {'argv': list(builder.os.sys.argv),
                         'mode': 'static_source_snapshot_only', 'build_command_invoked': False})
    try:
        items = {}
        for key, (relative, expected, snapshot) in INPUTS.items():
            source = builder.ordinary(ROOT / relative)
            builder.require(builder.sha(source) == expected, 'Static input changed: ' + relative)
            dest = HERE / snapshot
            if not dest.parent.exists():
                builder.fresh(dest.parent)
                dest.parent.mkdir()
            builder.fresh(dest)
            shutil.copy2(source, dest)
            builder.require(builder.sha(dest) == builder.sha(source) == expected, 'Static snapshot changed')
            items[key] = {'source': relative, 'sha256': expected, 'snapshot': snapshot,
                          'ordinary_file_and_ancestors': True}
        record = {'inputs': items, 'original_inputs_unchanged': True,
                  'reference_builder_or_audit_not_used_for_ABI_conclusion': True,
                  'builder_sha256_at_preparation': builder.sha(HERE / 'codec_builder.py'),
                  'Image_v4_completion_not_asserted': True, 'module_build_invoked': False,
                  'ABI_verified': False, 'board_tested': False}
        builder.write_json(HERE / 'prepared-inputs-v1.json', record)
        builder.write_json(output / 'result.json', record)
        print(json.dumps({'static_inputs_snapshotted': len(items), 'module_build_invoked': False}))
    except Exception:
        (output / 'failure.traceback').write_text(traceback.format_exc())
        builder.write_json(output / 'failure.json', {'actual_prepare_failed': True,
                           'module_build_invoked': False, 'ABI_verified': False})
        raise


if __name__ == '__main__':
    main()
