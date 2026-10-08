#!/usr/bin/env python3
"""Seal narrow v2 evidence and verify original v1 snapshot/live files unchanged."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=HERE/'sealed-v2'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def main():
    inputs=read(HERE/'inputs-v2/manifest.json')
    for rel,item in inputs['input_files'].items():
        assert sha(HERE/'inputs-v2'/rel)==item['sha256'],rel
        assert sha(ROOT/item['source'])==item['sha256'],item['source']
    for name,expected in inputs['generated_tools_sha256'].items():
        assert sha(HERE/name)==expected,name
    old=read(HERE/'sealed-v1/manifest.json')
    assert sha(HERE/'sealed-v1/manifest.json')==inputs['old_sealed_v1_manifest_sha256']
    prefix=HERE.relative_to(ROOT).as_posix()+'/'
    assert len(old['files_sha256'])==84
    for rel,expected in old['files_sha256'].items():
        assert rel.startswith(prefix)
        assert sha(HERE/'sealed-v1/snapshot'/rel[len(prefix):])==expected,rel
        assert sha(ROOT/rel)==expected,rel
    build=HERE/'build/emmc-v2'
    emmc=read(build/'manifest.json')
    candidate=build/'audio-emmc-compatible.dtb'
    expected='5c09084fe0d456953d228cdd811b53ddca8fc74f0963a2fe00820e70265f8b72'
    assert candidate.stat().st_size==163305 and sha(candidate)==emmc['candidate_sha256']==expected
    assert emmc['baseline_sha256']==inputs['baseline_sha256']=='4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'
    audit_tool=load('emmc_audit_freeze_v2',HERE/'test-emmc-bridge-v2.py')
    audit=audit_tool.audit(candidate.read_bytes())
    assert audit['node_count']==962 and audit['property_count']==4886 and audit['phandle_count']==762
    assert len(audit['full_diff'])==1
    red=read(HERE/'build/baseline-red-v2-retry/result.json')
    green=read(HERE/'build/audit-green-v2/result.json')
    warning=read(HERE/'build/dtc-warning-audit-v2/result.json')
    match=read(HERE/'build/linux-match-v2/result.json')
    assert not red['accepted'] and red['reason']=='Deployed U-Boot eMMC compatible is missing'
    assert red['candidate_sha256']==emmc['baseline_sha256']
    assert green['accepted'] and green['candidate_sha256']==match['candidate_sha256']==expected
    assert len(green['negative_cases'])==21 and all(row['rejected'] for row in green['negative_cases'])
    for row in green['negative_cases']:
        bad=HERE/'build/audit-green-v2/rejected-dtbs'/(row['name']+'.dtb')
        assert sha(bad)==row['sha256']
        try:
            audit_tool.audit(bad.read_bytes())
        except (ValueError,KeyError,UnicodeError,struct.error):
            pass
        else:
            raise ValueError('Bad frozen DTB passed '+row['name'])
    assert len(emmc['real_libfdt_runs'])==3 and all(row['sha256']==expected and row['bytes']==163305 for row in emmc['real_libfdt_runs'])
    assert warning['decode_diagnostics_same'] and warning['encode_diagnostics_same'] and warning['new_dtc_diagnostics']==0
    assert len(emmc['dtc_runs'])==4
    norms={}
    for row in emmc['dtc_runs']:
        stem=build/'dtc'/row['stage']
        assert row['exit_code']==0 and sha(stem.with_suffix('.stdout'))==row['stdout_sha256'] and sha(stem.with_suffix('.stderr'))==row['stderr_sha256']
        norms[row['stage']]=stem.with_suffix('.stderr').read_bytes().replace(row['argv'][-1].encode(),b'<input>')
    assert norms['baseline-decode']==norms['candidate-decode'] and norms['baseline-encode']==norms['candidate-encode']
    semantic=audit_tool.load('dt-semantics-v2.py')
    for name,path in [('baseline',build/'audio-baseline.dtb'),('candidate',candidate)]:
        assert semantic.parse((build/'dtc'/(name+'-roundtrip.dtb')).read_bytes())==semantic.parse(path.read_bytes())
    assert match['baseline_sha256']==emmc['baseline_sha256']
    base_compatible=semantic.parse((build/'audio-baseline.dtb').read_bytes())['properties']['/sdhci@fe310000:compatible']
    assert match['baseline_compatible_hex']==base_compatible
    assert len(match['receipts'])==2
    match_dir=HERE/'build/linux-match-v2'
    assert sha(match_dir/'actual-of-match.c')==match['generated_c_sha256']
    match_tool=load('emmc_match_freeze_v2',HERE/'check-linux-match-v2.py')
    generated=(match_dir/'actual-of-match.c').read_text()
    function_inputs=[('drivers/of/property.c','const char *of_prop_next_string('),('drivers/of/base.c','static int __of_device_is_compatible('),('drivers/of/base.c','const struct of_device_id *__of_match_node(')]
    units={}
    for rel,signature in function_inputs:
        unit=match_tool.function((ROOT/'third_party/linux-rk3588'/rel).read_text(),signature)
        assert unit in generated
        units[signature]=hashlib.sha256(unit.encode()).hexdigest()
    for row in match['receipts']:
        name=row['mode']
        assert row['passed']==row['total']==7 and row['compile_exit_code']==row['run_exit_code']==0
        assert sha(match_dir/name)==row['binary_sha256']
        assert sha(match_dir/(name+'-run.stdout'))==row['stdout_sha256']
        assert sha(match_dir/(name+'-run.stderr'))==row['stderr_sha256']
        assert not (match_dir/(name+'-run.stderr')).read_bytes()
        assert not (match_dir/(name+'-compile.stderr')).read_bytes()
        assert (match_dir/(name+'-run.stdout')).read_text().count('PASS ')==7
    for report in (emmc,match):
        for rel,digest in report['inputs_sha256'].items():
            assert sha(ROOT/rel)==digest,rel
    OUT.mkdir(exist_ok=False)
    files={}
    sources=[HERE/name for name in ('PLAN-v2.md','README-v2.md','prepare-tools-v2.py','freeze-results-v2.py',*inputs['generated_tools_sha256'].keys())]
    for folder in ('inputs-v2','build/emmc-v2','build/baseline-red-v2-retry','build/audit-green-v2','build/dtc-warning-audit-v2','build/linux-match-v2'):
        sources.extend(path for path in (HERE/folder).rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    sources.append(HERE/'build/wsl-launch-failure-v2.json')
    for path in sources:
        rel=path.relative_to(HERE)
        target=OUT/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        assert not target.exists()
        shutil.copyfile(path,target)
        files[rel.as_posix()]=sha(path)
        assert sha(target)==files[rel.as_posix()]
    manifest=OUT/'manifest.json'
    manifest.write_text(json.dumps({'files_sha256':files,'source_scope':'v2 tools/inputs/outputs only','old_sealed_v1_snapshot_and_live_files_sha_checked':84},indent=2)+'\n',newline='\n')
    receipt={'status':'OFFLINE_SHARED_DT_SINGLE_EMMC_COMPATIBLE_CHANGE',
        'manifest_sha256':sha(manifest),'files':len(files),'baseline_sha256':emmc['baseline_sha256'],'baseline_bytes':163285,
        'candidate_sha256':expected,'candidate_bytes':163305,'candidate_path':'build/emmc-v2/audio-emmc-compatible.dtb',
        'nodes':962,'properties':4886,'phandles':762,'only_compatible_changed':True,
        'real_libfdt_builds':3,'dtc_runs_exit0':4,'decode_and_encode_diagnostics_exact_after_path_normalization':True,
        'dtc_new_diagnostics':0,'negative_dtbs_rejected':21,'linux_matcher_host':'7/7','linux_matcher_asan_ubsan':'7/7',
        'linux_matcher_real_input_baseline_and_candidate':'rk3568_drvdata','actual_function_hashes':units,
        'old_sealed_v1_manifest_sha256':inputs['old_sealed_v1_manifest_sha256'],'old_v1_snapshot_and_live_files_unchanged':84,
        'version_inputs':19,'first_red_launcher_failed_before_script':True,'actual_red_retry_rejected':True,
        'usb_device_or_battery_candidates_merged':False,'usb_power_audio_chosen_phandles_reserves_unchanged':True,
        'early_dm_tested':False,'emmc_probe_io_tested':False,'usb_recovery_tested':False,'formal_flash_ready':False,
        'formal_boot_package_generated':False,'image_built':False,'audio_package_modified':False,'kernel_config_modified':False,
        'hardware_or_network_access':False,'wsl_tun_network_changed':False,
        'limits':['Overlay-applied tested Linux tree only; not proof a pre-overlay formal shared boot package is ready.','No deployed U-Boot DM rebuild, eMMC I/O, AVB/partition load or USB recovery/electrical test.','Actual OF matcher tests model node/property reads only, not driver probe/MMIO.']}
    record=OUT/'receipt.json'
    record.write_text(json.dumps(receipt,indent=2)+'\n',newline='\n')
    for rel,digest in files.items():
        assert sha(OUT/rel)==digest
    print(json.dumps({'receipt':str(record),'receipt_sha256':sha(record),'manifest_sha256':sha(manifest),'files':len(files),'candidate_sha256':expected}))

if __name__=='__main__':
    main()
