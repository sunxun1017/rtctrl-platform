#!/usr/bin/env python3
"""Execute the real readelf/nm/objcopy helper on frozen old codec bytes only."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    spec = importlib.util.spec_from_file_location('helper_v3', HERE / 'audio-package-v3.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    runtime = ROOT / 'outputs/rk3568-audio-runtime-20261005'
    module_path = runtime / 'build/integrated-codec-v1/modules/snd-soc-rk817.ko'
    binary = core.read_ordinary(module_path)
    core.require(core.metadata(binary)['sha256'] == 'e0aecc775367f93555c5776938102d419865a19128b25f64d74a8e9df387ca80',
                 'Exact frozen old codec fixture')
    record = core.unique_json(core.read_ordinary(runtime / 'build/integrated-codec-v1/manifest.json'))
    exports = {}
    data = core.read_ordinary(runtime / 'build/integration-v1/Module.symvers')
    for line in data.decode().splitlines():
        fields = line.split()
        exports[fields[1]] = {'provider': fields[2], 'export_type': fields[3], 'crc': fields[0],
                             'namespace': fields[4] if len(fields) > 4 else ''}
    actual = core.codec_elf_info(binary, exports)
    core.require(actual == record['module'], 'Actual old ELF audit equals frozen old manifest')
    core.require(core.read_ordinary(module_path) == binary, 'Original old codec remained read-only')
    output = core.fresh_directory(HERE / 'build/elf-helper-old-v3')
    result = {'scope': 'ACTUAL_ELF_HELPER_ON_FROZEN_OLD_CODEC_NOT_NEW_IMAGE_OR_NEW_CODEC_ACCEPTANCE',
              'core_source': core.metadata(core.read_ordinary(HERE / 'audio-package-v3.py')),
              'test_source': core.metadata(Path(__file__).read_bytes()), 'actual_info': actual,
              'source_module_unchanged': True, 'passed': 2, 'total': 2, 'board_tested': False}
    core.write_new(output / 'result.json', core.json_bytes(result))
    print(core.json_bytes({'passed': 2, 'total': 2, 'imports': len(actual['imports']), 'source_module_unchanged': True}).decode())


if __name__ == '__main__':
    main()
