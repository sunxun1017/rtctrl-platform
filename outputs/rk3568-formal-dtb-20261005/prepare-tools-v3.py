#!/usr/bin/env python3
"""Snapshot actual audio-v3 inputs and make narrow copies of the existing v2 tools."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/components/dtb'
BASE_SHA = 'c36b140c0ad18b79c3976f64239ef02251fc6986893afad7c474126725eb1e8b'
OLD_BASE = 'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb'
OLD_SHA = '4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    inputs = HERE / 'inputs-v3'
    assert not inputs.exists()
    prior = json.loads((HERE / 'inputs-v2/manifest.json').read_text())
    sources = {item['source']: item['sha256'] for item in prior['input_files'].values()}
    for name in ('build-emmc-bridge-v2.py', 'test-emmc-bridge-v2.py', 'check-linux-match-v2.py', 'verify-dtc-warnings-v2.py'):
        sources[(HERE / name).relative_to(ROOT).as_posix()] = sha(HERE / name)
    additions = [
        BASE, 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/manifest.json',
        'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/receipt.json',
        'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/audit.json',
        'outputs/rk3568-audio-package-20261005/audio-package-v3.py',
        'outputs/rk3568-audio-package-20261005/README-v3.md',
        'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/audio-ram-shim.dtb',
        'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/overlay-entry0.dtbo',
        'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/manifest.json',
        'outputs/rk3568-backup-linux-20261003/original/dtbo.img',
        'outputs/rk3568-boot-package-20261005/audit-boot.py',
        'outputs/rk3568-boot-package-20261005/build-uart-shim-v2.py',
        'outputs/rk3568-boot-package-20261005/build-roundtrip.py',
        'outputs/rk3568-boot-package-20261005/README-v2.md',
        'outputs/rk3568-boot-package-20261005/PLAN-v2.md',
        'outputs/rk3568-formal-dtb-20261005/build/emmc-v2/audio-emmc-compatible.dtb',
        'outputs/rk3568-formal-dtb-20261005/sealed-v1/manifest.json',
        'outputs/rk3568-formal-dtb-20261005/sealed-v2/manifest.json',
        'outputs/rk3568-formal-dtb-20261005/sealed-v2/receipt.json',
    ]
    for rel in additions:
        sources[rel] = sha(ROOT / rel)
    assert sources[BASE] == BASE_SHA and (ROOT / BASE).stat().st_size == 163204
    assert sources[OLD_BASE] == OLD_SHA
    assert sha(ROOT / 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/boot-padded.img') == '5d9e5de346a307edff9dc034f2b396e949b85d83564c1b6cfe9b62467a6ff8ab'
    for rel, expected in sources.items():
        assert sha(ROOT / rel) == expected, rel
    inputs.mkdir()
    records = {}
    for rel, expected in sources.items():
        target = inputs / 'snapshot' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
        assert sha(target) == expected
        records[rel] = {'sha256': expected, 'bytes': target.stat().st_size}
    generated = {}
    for stem in ('build-emmc-bridge', 'test-emmc-bridge', 'check-linux-match', 'verify-dtc-warnings'):
        text = (HERE / (stem + '-v2.py')).read_text()
        if stem != 'verify-dtc-warnings':
            assert text.count(OLD_BASE) == 1 and text.count(OLD_SHA) == 1
            text = text.replace(OLD_BASE, BASE).replace(OLD_SHA, BASE_SHA)
            if stem in ('test-emmc-bridge', 'check-linux-match'):
                assert text.count('len(baseline) != 163285' if stem == 'check-linux-match' else 'len(baseline) == 163285') == 1
                text = text.replace('len(baseline) != 163285', 'len(baseline) != 163204')
                text = text.replace('len(baseline) == 163285', 'len(baseline) == 163204')
        if stem == 'build-emmc-bridge':
            needle = "    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\\n')"
            assert text.count(needle) == 1
            extra = "    spec = importlib.util.spec_from_file_location('emmc_overlay_v3', HERE / 'overlay-contract-v3.py')\n    contract = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(contract)\n    manifest['overlay_contract'] = contract.verify_pipeline(out, baseline, candidate)\n"
            text = text.replace(needle, extra + needle)
        target = HERE / (stem + '-v3.py')
        assert not target.exists()
        target.write_text(text, newline='\n')
        generated[target.name] = sha(target)
    report = {'actual_pre_overlay_path': BASE, 'actual_pre_overlay_sha256': BASE_SHA,
              'actual_pre_overlay_bytes': 163204, 'input_files': records,
              'generated_tools_sha256': generated,
              'referenced_large_input': {'path': 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3/boot-padded.img',
                                        'bytes': 41943040, 'sha256': '5d9e5de346a307edff9dc034f2b396e949b85d83564c1b6cfe9b62467a6ff8ab'},
              'tool_scope': 'v2 BASE path/SHA/size changes; builder calls actual package+real overlay contract verifier',
              'board_access': False, 'audio_package_modified': False}
    (inputs / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n', newline='\n')
    print(json.dumps({'snapshots': len(records), 'generated_tools': list(generated)}))


if __name__ == '__main__':
    main()
