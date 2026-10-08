#!/usr/bin/env python3
"""Actual validate_codec function with frozen old bytes and explicit FS/ELF fixtures."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = HERE / 'build' / args.out
    out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('closure_v3', HERE / 'audio-package-v3.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    runtime = ROOT / 'outputs/rk3568-audio-runtime-20261005'
    manifest_data = (runtime / 'build/integration-v1/manifest.json').read_bytes()
    image_manifest = json.loads(manifest_data)
    image = (runtime / 'build/integration-v1/Image').read_bytes()
    codec = json.loads((runtime / 'build/integrated-codec-v1/manifest.json').read_bytes())
    module = (runtime / 'build/integrated-codec-v1/modules/snd-soc-rk817.ko').read_bytes()
    assert core.metadata(image)['sha256'] == image_manifest['image_sha256'] == codec['image_sha256']
    assert core.metadata(module)['sha256'] == codec['module']['sha256']

    def old_path(path):
        name = Path(path).relative_to(ROOT).as_posix()
        name = name.replace('.deps/kernel/aiot-3568pq-audio-v2/', '.deps/kernel/aiot-3568pq-audio-v1/')
        name = name.replace('/build/integration-v2/', '/build/integration-v1/')
        name = name.replace('/build/integrated-codec-v2/', '/build/integrated-codec-v1/')
        name = name.replace('/build-integrated-codec-v2.py', '/build-integrated-codec.py')
        return ROOT / name

    # Only this test's explicit filesystem fixture maps new path names to old frozen bytes.
    core.read_ordinary = lambda path, limit=64 * 1024 * 1024: old_path(path).read_bytes()
    # These helpers model the complete frozen old ABI and actual old ELF audit result.
    # New real production checks must independently execute both actual helpers.
    core.codec_abi_names = lambda: set(codec['abi_inventory'])
    core.codec_elf_info = lambda binary, exports: codec['module']
    cases = []

    def test(name, record, expected_rejection=None):
        try:
            core.validate_codec(record, module, image, manifest_data, image_manifest)
            ok = expected_rejection is None
            evidence = 'accepted'
        except ValueError as error:
            evidence = str(error)
            ok = expected_rejection is not None and expected_rejection in evidence
        cases.append({'name': name, 'passed': ok, 'evidence': evidence})

    test('complete-real-old-codec-byte-fixture', codec)
    truncated = copy.deepcopy(codec)
    truncated['abi_inventory'] = {n: v for n, v in codec['abi_inventory'].items() if n in ('.config', 'Module.symvers', 'vmlinux.symvers')}
    test('missing-ABI-headers-rejected', truncated, 'exact ordinary file set')
    missing_import = copy.deepcopy(codec)
    del missing_import['module']['imports'][next(iter(missing_import['module']['imports']))]
    test('missing-module-import-rejected', missing_import, 'actual complete ELF audit binding')
    result = {'scope': 'ACTUAL_VALIDATE_CODEC_WITH_FROZEN_OLD_BYTES_AND_EXPLICIT_FS_ABI_ELF_FIXTURES',
              'production_Image_faked': False, 'new_actual_ELF_or_ABI_helper_executed': False,
              'core_source': core.metadata((HERE / 'audio-package-v3.py').read_bytes()),
              'test_source': core.metadata(Path(__file__).read_bytes()),
              'Image': core.metadata(image), 'codec_module': core.metadata(module),
              'passed': sum(c['passed'] for c in cases), 'total': len(cases), 'cases': cases,
              'board_tested': False, 'formal_flash_ready': False}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] == result['total'] else 1)


if __name__ == '__main__':
    main()
