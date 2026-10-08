#!/usr/bin/env python3
"""Additive v3 migration of frozen v2 packaging. Never overwrite existing files."""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(name, value):
    with (HERE / name).open('xb') as stream:
        stream.write(value.encode())


def change(text, old, new, count=1):
    assert text.count(old) == count, (old, text.count(old))
    return text.replace(old, new)


def main():
    assert '"passed": 0' in (HERE / 'build/transition-red-v2/result.json').read_text()
    text = (HERE / 'audio-package-v2.py').read_text()
    text = change(text, "PRODUCTION = RUNTIME + 'build/integration-v1/'", "PRODUCTION = RUNTIME + 'build/integration-v2/'")
    text = change(text, "CPU_MANIFEST = '92344de6c38aeb3353134150ec9bca75fad84dc3d2071e1bbd7d611fd0d73b56'",
                  "CPU_MANIFEST = '39fd8b0f1ccabd5d93d26ba540786865740a2b4c29295e392e7dcf4d65393e13'\n" +
                  (HERE / 'runtime-policy-v3.inc.py').read_text() + '\n')
    text = change(text, "manifest.get('cpu_manifest_sha256') == CPU_MANIFEST",
                  "manifest.get('cpu_v10_manifest_sha256') == CPU_V10_MANIFEST and\n            manifest.get('cpu_source_sha256') == CPU_SOURCE and\n            manifest.get('cpu_v11_inventory_sha256') == CPU_INVENTORY and\n            manifest.get('battery_algorithm_enabled') is False")
    text = change(text, "require(gate.get('accepted_for_offline_integration') is True, 'Independent C3 integration gate required')",
                  "require(gate.get('accepted_for_offline_integration') is True and\n            gate.get('cpu_v11_independent_review_completed') is True, 'Independent C3/CPU v11 integration gate required')")
    text = change(text, "    require(set(patches) == expected_public | {c3_patch, cpu_patch}, 'Image exact patch series')",
                  "    delta = RUNTIME + 'cpu-lifecycle-v11/source/delta-v10-v11.patch'\n" +
                  "    require(set(patches) == expected_public | {c3_patch, cpu_patch, delta}, 'Image exact patch series')\n" +
                  "    require(patches.get(delta) == bound.get(delta) == CPU_DELTA, 'Image CPU v11 delta identity')\n" +
                  "    for name, expected in CPU_FILES.items():\n" +
                  "        require(bound.get(name) == expected, 'Image review CPU v11 freeze binding: ' + name)\n" +
                  "        require(metadata(read_ordinary(relative_path(name)))['sha256'] == expected, 'CPU v11 frozen input changed')\n" +
                  "    require(metadata(read_ordinary(relative_path('.deps/kernel-source/aiot-3568pq-audio-v2/sound/soc/rockchip/rockchip_i2s_tdm.c')))['sha256'] == CPU_SOURCE, 'Actual new CPU source binding')")
    text = change(text, "RUNTIME + 'build-audio-image.py'", "RUNTIME + 'build-audio-image-v2.py'")
    text = change(text, "    return {'kernel': image, 'mode': 'RAM_ONLY_NOT_FLASH_READY',",
                  "    runtime, blobs = runtime_inputs(image, manifest_data, manifest)\n" +
                  "    return {'kernel': image, 'runtime': runtime, 'runtime_blobs': blobs, 'mode': 'RAM_ONLY_NOT_FLASH_READY',")
    text = change(text, "    output = fresh_directory(out)\n    components = output / 'components'",
                  "    require(image_inputs['mode'] != 'RAM_ONLY_NOT_FLASH_READY' or\n            set(image_inputs.get('runtime_blobs', {})) == set(RUNTIME_FIXED) | {'snd-soc-rk817.ko'}, 'Complete production runtime sidecars required')\n" +
                  "    output = fresh_directory(out)\n" +
                  "    if image_inputs['mode'] == 'RAM_ONLY_NOT_FLASH_READY':\n" +
                  "        runtime = output / 'runtime'\n        runtime.mkdir()\n" +
                  "        for name, blob in image_inputs['runtime_blobs'].items():\n            write_new(runtime / name, blob)\n" +
                  "        write_new(runtime / 'SHA256SUMS', runtime_sums(image_inputs['runtime_blobs']))\n" +
                  "    components = output / 'components'")
    text = change(text, "if key != 'kernel'", "if key not in ('kernel', 'runtime_blobs')", count=2)
    text = change(text, "    expected_image = {key: value for key, value in image_inputs.items() if key not in ('kernel', 'runtime_blobs')}\n",
                  "    if image_inputs['mode'] == 'RAM_ONLY_NOT_FLASH_READY':\n" +
                  "        for name, blob in image_inputs['runtime_blobs'].items():\n" +
                  "            require(read_ordinary(path / 'runtime' / name) == blob, 'Runtime sidecar content binding: ' + name)\n" +
                  "        require(read_ordinary(path / 'runtime/SHA256SUMS') == runtime_sums(image_inputs['runtime_blobs']), 'Runtime exact checksum list')\n" +
                  "    expected_image = {key: value for key, value in image_inputs.items() if key not in ('kernel', 'runtime_blobs')}\n")
    for old, new in [('audio-package-v2.py', 'audio-package-v3.py'), ('build-audio-package-v2.py', 'build-audio-package-v3.py'),
                     ('audit-audio-package-v2.py', 'audit-audio-package-v3.py'), ('test-audio-package-v2.py', 'test-audio-package-v3.py'),
                     ('README-v2.md', 'README-v3.md'), ('PLAN-v2.md', 'PLAN-v3.md')]:
        text = change(text, "'" + old + "'", "'" + new + "'", count=2)
    write('audio-package-v3.py', text)
    for old, new in [('build-audio-package-v2.py', 'build-audio-package-v3.py'), ('audit-audio-package-v2.py', 'audit-audio-package-v3.py')]:
        wrapper = (HERE / old).read_text().replace('integration-v1', 'integration-v2').replace('audio-package-v2.py', 'audio-package-v3.py')
        write(new, wrapper)
    write('test-audio-package-v3.py', (HERE / 'test-audio-package-v2.py').read_text().replace('audio-package-v2.py', 'audio-package-v3.py').replace('build-audio-package-v2.py', 'build-audio-package-v3.py'))
    for old, new in [('run-production-v2.py', 'run-production-v3.py')]:
        write(new, (HERE / old).read_text().replace('review-gate-v2.json', 'review-gate-v3.json').replace('integration-v1', 'integration-v2').replace('production-cli-v2', 'production-cli-v3').replace('ram-audio-v2', 'ram-audio-v3').replace('audit-production-v2', 'audit-production-v3').replace('audio-package-v2.py', 'audio-package-v3.py').replace('timeout=120', 'timeout=600'))


if __name__ == '__main__':
    main()
