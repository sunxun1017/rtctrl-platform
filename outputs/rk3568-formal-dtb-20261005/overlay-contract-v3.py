#!/usr/bin/env python3
"""Use existing parsers and actual libfdt to close the pre/post-overlay boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / 'outputs/rk3568-boot-package-20261005'
AUDIO = ROOT / 'outputs/rk3568-audio-package-20261005/build/ram-audio-v3'
POST_BASE = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb'
POST_V2 = HERE / 'build/emmc-v2/audio-emmc-compatible.dtb'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def load(name):
    spec = importlib.util.spec_from_file_location('emmc_v3_' + name.replace('-', '_'), PACKAGE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_inputs():
    locked = json.loads((HERE / 'inputs-v3/manifest.json').read_text())
    for rel, record in locked['input_files'].items():
        blob = (ROOT / rel).read_bytes()
        require(len(blob) == record['bytes'] and sha(blob) == record['sha256'], 'Locked input changed: ' + rel)
    record = locked['referenced_large_input']
    boot = (ROOT / record['path']).read_bytes()
    require(len(boot) == record['bytes'] and sha(boot) == record['sha256'], 'Actual audio-v3 complete package changed')
    return boot


def check_candidate(pre, candidate):
    semantic = load('dt-semantics-v2.py')
    before, after = semantic.parse(pre), semantic.parse(candidate)
    old = before['properties']['/sdhci@fe310000:compatible']
    expected = {'/sdhci@fe310000:compatible': {'before': old, 'after': old + b'snps,dwcmshc-sdhci\0'.hex()}}
    require(semantic.diff(before, after) == expected, 'Only pre-overlay eMMC compatible may change')
    require(semantic.phandles(before) == semantic.phandles(after), 'Pre-overlay phandles changed')
    return expected


def verify_pipeline(out, pre, candidate):
    boot = verify_inputs()
    parser = load('audit-boot.py')
    package = parser.inspect_boot(boot, expected_concat_count=1)
    manifest = json.loads((AUDIO / 'manifest.json').read_text())
    receipt = json.loads((AUDIO / 'receipt.json').read_text())
    require(manifest['inputs']['dtb']['sha256'] == sha(pre) == receipt['files']['components/dtb']['sha256'], 'Audio-v3 input/receipt DT identity')
    require(receipt['files']['boot-padded.img']['sha256'] == sha(boot), 'Audio-v3 receipt package identity')
    require(receipt['files']['manifest.json']['sha256'] == sha((AUDIO / 'manifest.json').read_bytes()), 'Audio-v3 manifest receipt identity')
    component = next(row for row in package['components'] if row['name'] == 'dtb')
    require(boot[component['offset']:component['offset'] + component['bytes']] == pre, 'Actual header-v2 component differs from pre-overlay input')
    second = next(row for row in package['components'] if row['name'] == 'second')
    resource = boot[second['offset']:second['offset'] + second['bytes']]
    dt_entries = [row for row in package['resource']['entries'] if row['path'].endswith('.dtb')]
    require(len(dt_entries) == 9, 'Actual RSCE DT count')
    for row in dt_entries:
        require(resource[row['offset']:row['offset'] + row['bytes']] == pre and row['hash_verified'], 'Actual RSCE input differs: ' + row['path'])
    check_candidate(pre, candidate)
    dtbo = (ROOT / manifest['inputs']['dtbo']['path']).read_bytes()
    require(sha(dtbo) == manifest['inputs']['dtbo']['sha256'], 'Original DTBO binding')
    overlay = load('build-uart-shim-v2.py').overlay_entry(dtbo)
    original_entry = ROOT / 'outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/overlay-entry0.dtbo'
    require(overlay == original_entry.read_bytes(), 'Entry0 differs from actual audio contract')
    semantic = load('dt-semantics-v2.py')
    real = load('libfdt-v2.py').RealLibFdt()
    runs = []
    post_base, post_v2 = POST_BASE.read_bytes(), POST_V2.read_bytes()
    for number in range(1, 4):
        base_report, applied_base = real.apply(pre, overlay)
        require(base_report['status'] == 0 and applied_base == post_base, 'Actual pre-overlay base fails original post-overlay identity')
        report, applied = real.apply(candidate, overlay)
        require(report['status'] == 0 and applied is not None, 'Candidate real overlay failed')
        require(semantic.parse(applied) == semantic.parse(post_v2), 'Applied v3 differs from v2 complete semantics')
        require(semantic.phandles(semantic.parse(applied)) == semantic.phandles(semantic.parse(post_v2)), 'Applied phandles differ')
        require(semantic.diff(semantic.parse(pre), semantic.parse(applied_base)) == semantic.diff(semantic.parse(candidate), semantic.parse(applied)), 'Overlay transition changed')
        runs.append({'number': number, 'baseline_apply': base_report, 'candidate_apply': report,
                     'applied_bytes': len(applied), 'applied_sha256': sha(applied),
                     'full_semantics_equal_to_v2': True, 'bytes_equal_to_v2': applied == post_v2})
    require(len({row['applied_sha256'] for row in runs}) == 1, 'Overlay output non-deterministic')
    (out / 'overlay-entry0.dtbo').write_bytes(overlay)
    (out / 'applied-baseline-audit-only.dtb').write_bytes(applied_base)
    (out / 'applied-emmc-audit-only.dtb').write_bytes(applied)
    for name, blob in [('pre-baseline', pre), ('pre-candidate', candidate), ('post-baseline', applied_base), ('post-candidate', applied)]:
        (out / (name + '-semantics.json')).write_text(json.dumps(semantic.parse(blob), indent=2) + '\n')
    return {'status': 'PRE_OVERLAY_ONLY_CANDIDATE_POST_OVERLAY_AUDIT_ONLY',
            'actual_audio_package_sha256': sha(boot), 'actual_component_offset': component['offset'],
            'actual_header_v2_single_dt_verified': True, 'actual_rsce_nine_dt_bytes_verified': True,
            'actual_resource_dt_paths': [row['path'] for row in dt_entries],
            'original_dtbo_sha256': sha(dtbo), 'entry0_bytes': len(overlay), 'entry0_sha256': sha(overlay),
            'pre_baseline_sha256': sha(pre), 'pre_candidate_sha256': sha(candidate),
            'post_baseline_sha256': sha(post_base), 'v2_post_candidate_sha256': sha(post_v2),
            'post_candidate_sha256': sha(applied), 'post_candidate_bytes': len(applied),
            'overlay_only_diff': semantic.diff(semantic.parse(candidate), semantic.parse(applied)),
            'real_libfdt_apply_pairs': runs,
            'packaged_candidate_role': 'audio-emmc-compatible.dtb is pre-overlay; applied-emmc-audit-only.dtb must not be packaged',
            'exact_deployed_libfdt': False, 'board_tested': False, 'early_dm_tested': False,
            'new_boot_package_generated': False, 'flash_authorized': False}
