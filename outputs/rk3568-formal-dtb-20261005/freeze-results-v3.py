#!/usr/bin/env python3
"""Seal actual pre/overlay proof, bounded regressions, and unchanged older evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    inputs = read(HERE / 'inputs-v3/manifest.json')
    for rel, row in inputs['input_files'].items():
        assert sha(ROOT / rel) == sha(HERE / 'inputs-v3/snapshot' / rel) == row['sha256'], rel
        assert (ROOT / rel).stat().st_size == row['bytes']
    for name, digest in inputs['generated_tools_sha256'].items():
        assert sha(HERE / name) == digest
    big = inputs['referenced_large_input']
    assert sha(ROOT / big['path']) == big['sha256'] and (ROOT / big['path']).stat().st_size == big['bytes']
    previous = {}
    v1 = read(HERE / 'sealed-v1/manifest.json')
    prefix = HERE.relative_to(ROOT).as_posix() + '/'
    for rel, digest in v1['files_sha256'].items():
        assert rel.startswith(prefix)
        assert sha(HERE / 'sealed-v1/snapshot' / rel[len(prefix):]) == sha(ROOT / rel) == digest, rel
    previous['v1'] = {'manifest_sha256': sha(HERE / 'sealed-v1/manifest.json'), 'snapshot_and_live_files': len(v1['files_sha256'])}
    v2 = read(HERE / 'sealed-v2/manifest.json')
    for rel, digest in v2['files_sha256'].items():
        assert sha(HERE / 'sealed-v2' / rel) == sha(HERE / rel) == digest, rel
    previous['v2'] = {'manifest_sha256': sha(HERE / 'sealed-v2/manifest.json'), 'snapshot_and_live_files': len(v2['files_sha256'])}
    assert previous['v1']['snapshot_and_live_files'] == 84 and previous['v2']['snapshot_and_live_files'] == 80
    build = HERE / 'build/emmc-v3'
    emmc = read(build / 'manifest.json')
    pre, post = build / 'audio-emmc-compatible.dtb', build / 'applied-emmc-audit-only.dtb'
    assert sha(pre) == emmc['candidate_sha256'] == '08ddd2ad4040ae298dae55ecb928c86672090d9d9bd1f889875ffd1b1daab700'
    assert pre.stat().st_size == emmc['candidate_bytes'] == 163224
    assert sha(post) == '5c09084fe0d456953d228cdd811b53ddca8fc74f0963a2fe00820e70265f8b72' and post.stat().st_size == 163305
    audit = load('test-emmc-bridge-v3.py').audit(pre.read_bytes())
    post_audit = load('test-emmc-bridge-v2.py').audit(post.read_bytes())
    assert (audit['node_count'], audit['property_count'], audit['phandle_count']) == (962, 4885, 762)
    assert (post_audit['node_count'], post_audit['property_count'], post_audit['phandle_count']) == (962, 4886, 762)
    semantic = load('test-emmc-bridge-v3.py').load('dt-semantics-v2.py')
    assert semantic.parse(post.read_bytes()) == semantic.parse((HERE / 'build/emmc-v2/audio-emmc-compatible.dtb').read_bytes())
    assert len(emmc['real_libfdt_runs']) == 3 and all(row['sha256'] == sha(pre) for row in emmc['real_libfdt_runs'])
    overlay = emmc['overlay_contract']
    assert overlay['actual_header_v2_single_dt_verified'] and overlay['actual_rsce_nine_dt_bytes_verified']
    assert len(overlay['real_libfdt_apply_pairs']) == 3
    for row in overlay['real_libfdt_apply_pairs']:
        assert row['baseline_apply']['status'] == row['candidate_apply']['status'] == 0
        assert row['bytes_equal_to_v2'] and row['full_semantics_equal_to_v2'] and row['applied_sha256'] == sha(post)
    assert len(overlay['overlay_only_diff']) == 3 and sha(build / 'overlay-entry0.dtbo') == overlay['entry0_sha256']
    red = read(HERE / 'build/baseline-red-v3/result.json')
    assert not red['accepted'] and red['reason'] == 'Deployed U-Boot eMMC compatible is missing'
    for folder, tool_name, candidate in [('audit-pre-green-v3', 'test-emmc-bridge-v3.py', pre), ('audit-post-green-v3', 'test-emmc-bridge-v2.py', post)]:
        green = read(HERE / 'build' / folder / 'result.json')
        assert green['accepted'] and green['candidate_sha256'] == sha(candidate)
        assert len(green['negative_cases']) == 21
        tool = load(tool_name)
        for row in green['negative_cases']:
            bad = HERE / 'build' / folder / 'rejected-dtbs' / (row['name'] + '.dtb')
            assert row['rejected'] and sha(bad) == row['sha256']
            try:
                tool.audit(bad.read_bytes())
            except (ValueError, KeyError, UnicodeError):
                pass
            else:
                raise AssertionError('Sealed bad DTB passed ' + row['name'])
    warning = read(HERE / 'build/dtc-warning-audit-v3/result.json')
    assert warning['decode_diagnostics_same'] and warning['encode_diagnostics_same'] and warning['new_dtc_diagnostics'] == 0
    normalized = {}
    assert len(emmc['dtc_runs']) == 4
    for row in emmc['dtc_runs']:
        stem = build / 'dtc' / row['stage']
        assert row['exit_code'] == 0 and sha(stem.with_suffix('.stdout')) == row['stdout_sha256'] and sha(stem.with_suffix('.stderr')) == row['stderr_sha256']
        normalized[row['stage']] = stem.with_suffix('.stderr').read_bytes().replace(row['argv'][-1].encode(), b'<input>')
    for stage in ('decode', 'encode'):
        assert normalized['baseline-' + stage] == normalized['candidate-' + stage]
    for name, path in [('baseline', build / 'audio-baseline.dtb'), ('candidate', pre)]:
        assert semantic.parse((build / 'dtc' / (name + '-roundtrip.dtb')).read_bytes()) == semantic.parse(path.read_bytes())
    boundaries = read(HERE / 'build/overlay-boundaries-v3/result.json')
    assert len(boundaries['negative_cases']) == boundaries['negative_cases_rejected'] == 12
    assert boundaries['positive_control_sha256'] == sha(post) and boundaries['positive_apply']['status'] == 0
    actual_failures = 0
    for row in boundaries['negative_cases']:
        assert row['rejected']
        if 'apply' in row:
            actual_failures += 1
            result = row['apply']
            assert result['status'] < 0 and result['restored_exact'] and result['failure_code_preserved_after_restore']
            assert result['backup_sha256'] == result['restored_sha256'] and not row['applied_tree_returned']
            assert sha(HERE / 'build/overlay-boundaries-v3' / (row['name'] + '-base.dtb')) == row['base_sha256']
            assert sha(HERE / 'build/overlay-boundaries-v3' / (row['name'] + '-overlay.dtbo')) == row['overlay_sha256']
        else:
            assert sha(HERE / 'build/overlay-boundaries-v3' / (row['name'] + '.bin')) == row['sha256']
    assert actual_failures == 5
    match_dir = HERE / 'build/linux-match-v3'
    matcher = read(match_dir / 'result.json')
    assert matcher['candidate_sha256'] == sha(pre) and matcher['baseline_sha256'] == emmc['baseline_sha256']
    assert sha(match_dir / 'actual-of-match.c') == matcher['generated_c_sha256']
    match_tool = load('check-linux-match-v3.py')
    generated = (match_dir / 'actual-of-match.c').read_text()
    units = {}
    for rel, signature in [('drivers/of/property.c', 'const char *of_prop_next_string('), ('drivers/of/base.c', 'static int __of_device_is_compatible('), ('drivers/of/base.c', 'const struct of_device_id *__of_match_node(')]:
        unit = match_tool.function((ROOT / 'third_party/linux-rk3588' / rel).read_text(), signature)
        assert unit in generated
        units[signature] = hashlib.sha256(unit.encode()).hexdigest()
    assert len(matcher['receipts']) == 2
    for row in matcher['receipts']:
        mode = row['mode']
        assert row['passed'] == row['total'] == 7 and row['compile_exit_code'] == row['run_exit_code'] == 0
        assert sha(match_dir / mode) == row['binary_sha256']
        assert sha(match_dir / (mode + '-run.stdout')) == row['stdout_sha256'] and sha(match_dir / (mode + '-run.stderr')) == row['stderr_sha256']
        assert (match_dir / (mode + '-run.stdout')).read_text().count('PASS ') == 7
        assert not (match_dir / (mode + '-compile.stderr')).read_bytes() and not (match_dir / (mode + '-run.stderr')).read_bytes()
    for report in (emmc, matcher):
        for rel, digest in report['inputs_sha256'].items():
            assert sha(ROOT / rel) == digest, rel
    deployed = read(HERE / 'build/deployed-evidence-v3/result.json')
    raw = ROOT / deployed['raw_reference']['path']
    assert sha(raw) == deployed['raw_reference']['sha256']
    lines = raw.read_text().splitlines()
    assert len(deployed['selected_exact_lines']) == 5
    for row in deployed['selected_exact_lines']:
        assert lines[row['line'] - 1] == row['text']
    for rel, digest in deployed['references_sha256'].items():
        assert sha(ROOT / rel) == digest
    out = HERE / 'sealed-v3'
    out.mkdir(exist_ok=False)
    files = {}
    sources = [HERE / name for name in ('PLAN-v3.md', 'README-v3.md', 'prepare-tools-v3.py', 'overlay-contract-v3.py', 'test-overlay-contract-v3.py', 'record-deployed-evidence-v3.py', 'freeze-results-v3.py', *inputs['generated_tools_sha256'].keys())]
    for folder in ('inputs-v3', 'build/emmc-v3', 'build/baseline-red-v3', 'build/audit-pre-green-v3', 'build/audit-post-green-v3', 'build/overlay-boundaries-v3', 'build/dtc-warning-audit-v3', 'build/linux-match-v3', 'build/deployed-evidence-v3'):
        sources.extend(path for path in (HERE / folder).rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    for path in sources:
        rel = path.relative_to(HERE)
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        assert not target.exists()
        shutil.copyfile(path, target)
        files[rel.as_posix()] = sha(path)
        assert sha(target) == files[rel.as_posix()]
    manifest = out / 'manifest.json'
    manifest.write_text(json.dumps({'files_sha256': files, 'source_scope': 'new v3 offline tools/inputs/outputs only', 'previous_snapshots_and_live_checked': previous}, indent=2) + '\n', newline='\n')
    receipt = {'status': 'OFFLINE_SHARED_DT_PRE_OVERLAY_EMMC_BRIDGE_CANDIDATE', 'manifest_sha256': sha(manifest), 'files': len(files),
               'actual_audio_v3_pre_input_sha256': emmc['baseline_sha256'], 'actual_audio_v3_package_sha256': big['sha256'],
               'candidate_path': 'build/emmc-v3/audio-emmc-compatible.dtb', 'candidate_bytes': 163224, 'candidate_sha256': sha(pre),
               'post_audit_only_path': 'build/emmc-v3/applied-emmc-audit-only.dtb', 'post_audit_only_bytes': 163305, 'post_audit_only_sha256': sha(post),
               'post_full_semantics_and_bytes_equal_to_v2': True, 'pre_nodes': 962, 'pre_properties': 4885, 'phandles': 762,
               'only_pre_emmc_compatible_changed': True, 'actual_header_dt_and_nine_rsce_dt_verified': True,
               'version_inputs': len(inputs['input_files']), 'real_libfdt_builds': 3, 'real_overlay_apply_pairs': 3,
               'dtc_exit0_runs': 4, 'dtc_decode_encode_diagnostics_exact_after_path_normalization': True, 'dtc_new_diagnostics': 0,
               'pre_negative_dtbs_rejected': 21, 'post_negative_dtbs_rejected': 21, 'overlay_boundary_negative_cases_rejected': 12,
               'real_overlay_failure_restore_preserved_errors': 5, 'linux_matcher_host': '7/7', 'linux_matcher_asan_ubsan': '7/7',
               'linux_matcher_functions_sha256': units, 'previous_snapshots_and_live_unchanged': previous,
               'existing_actual_ram_boot_log_reference': deployed['raw_reference'], 'existing_overlay_success_log_lines': 5,
               'deployed_overlay_failure_not_exercised_here': True, 'exact_deployed_libfdt': False,
               'accepted_for_board': False, 'board_tested': False, 'early_dm_tested': False, 'emmc_probe_io_tested': False,
               'usb_recovery_tested': False, 'formal_flash_ready': False, 'flash_authorized': False,
               'image_generated': False, 'new_boot_package_generated': False, 'audio_package_modified': False,
               'usb_device_battery_candidates_merged': False, 'hardware_network_access': False, 'tun_or_wsl_service_changed': False,
               'limits': ['Pre-overlay finite DT candidate only; post file is audit-only and must not be packaged.', 'Kernel real libfdt is not exact deployed U-Boot libfdt; actual existing RAM log proves one successful overlay, not failed-overlay handling.', 'Existing CLI RAM trial retained original early DM; new RSCE early-DM/probe/provider/eMMC I/O and formal boot_android/AVB/partition path are not verified.', 'Actual Linux OF matcher models node/property access only; it does not execute the eMMC driver.', 'USB VBUS/ID/DMO and recovery remain unverified; no USB or gauge enabling.']}
    record = out / 'receipt.json'
    record.write_text(json.dumps(receipt, indent=2) + '\n', newline='\n')
    for rel, digest in files.items():
        assert sha(out / rel) == digest
    print(json.dumps({'receipt_sha256': sha(record), 'manifest_sha256': sha(manifest), 'files': len(files), 'pre_candidate_sha256': sha(pre), 'post_candidate_sha256': sha(post)}))


if __name__ == '__main__':
    main()
