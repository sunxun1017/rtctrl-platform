#!/usr/bin/env python3
"""Recheck all actual artifacts and seal only this Linux-only offline DT task."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct

HERE=Path(__file__).resolve().parent
OUT=HERE/'sealed-v2'
spec=importlib.util.spec_from_file_location('usb_freeze_contract',HERE/'usb-contract.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def main():
    baseline=C.inputs()
    build=HERE/'build/usb2-peripheral-v2'
    result=read(build/'result.json')
    assert result['baseline_sha256']==C.BASE_SHA
    assert result['candidate_sha256']=='facc02a3157fffd52a5459c911ee962293848223c9eef86b05491a2e61e1dc10'
    assert result['script_sha256']==sha(HERE/'build-candidate-v2.py')
    assert result['contract_sha256']==sha(HERE/'usb-contract.py')
    assert result['inputs_manifest_sha256']==sha(HERE/'inputs-v1/manifest.json')
    assert len(result['real_libfdt_runs'])==3
    for item in result['real_libfdt_runs']:
        path=build/f"usb2-peripheral-{item['number']}.dtb"
        assert sha(path)==item['sha256']==result['candidate_sha256'] and path.stat().st_size==item['bytes']==163303
        assert C.audit(path.read_bytes())['full_diff']==result['full_tree_audit']['full_diff']
    audit=C.audit((build/'usb2-peripheral-1.dtb').read_bytes())
    assert audit['dependency_graph']==read(build/'usb-dependency-graph.json')
    assert audit['dependency_graph']['node_count']==39
    assert audit['nodes']==962 and audit['properties']==4887 and audit['phandles']==762
    assert len(result['negative_binary_fixtures'])==29
    for item in result['negative_binary_fixtures']:
        blob=(build/'rejected-dtbs'/(item['name']+'.dtb')).read_bytes()
        assert C.sha(blob)==item['sha256'] and item['rejected']
        try:
            C.audit(blob)
        except (ValueError,KeyError,UnicodeError,struct.error):
            pass
        else:
            raise ValueError('Frozen negative passed: '+item['name'])
    assert len(result['dtc_runs'])==4
    for run in result['dtc_runs']:
        stem=build/'dtc'/run['stage']
        assert run['exit_code']==0
        assert sha(stem.with_suffix('.stdout'))==run['stdout_sha256']
        assert sha(stem.with_suffix('.stderr'))==run['stderr_sha256']
    norms={name:(build/'dtc'/(name+'-normalized.stderr')).read_bytes() for name in ('baseline-decode','candidate-decode','baseline-encode','candidate-encode')}
    assert norms['baseline-decode']==norms['candidate-decode']
    removed=(result['removed_warning']+'\n').encode()
    assert norms['baseline-encode'].count(removed)==1
    assert norms['baseline-encode'].replace(removed,b'',1)==norms['candidate-encode']
    assert not result['dtc_encode_diagnostics_same_after_path_and_location_normalization']
    assert result['dtc_encode_only_expected_warning_removed'] and result['dtc_encode_new_or_changed_messages']==0
    for label,path in [('baseline',build/'audio-linux-baseline.dtb'),('candidate',build/'usb2-peripheral-1.dtb')]:
        assert C.SEM.parse((build/'dtc'/(label+'-roundtrip.dtb')).read_bytes())==C.SEM.parse(path.read_bytes())
    assert read(HERE/'build/usb2-peripheral-v1/failed.json')['success'] is False
    assert read(HERE/'build/diagnostics-difference-v1/result.json')['only_removed_usb3_numeric_reference_warning']
    assert len(read(HERE/'build/native-plan-v1/result.json')['negative_fixtures'])==22
    OUT.mkdir(exist_ok=False)
    files={}
    for path in sorted(HERE.rglob('*')):
        if path.is_file() and OUT not in path.parents and '__pycache__' not in path.parts:
            rel=path.relative_to(HERE)
            target=OUT/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
            files[rel.as_posix()]=sha(path)
            assert sha(target)==files[rel.as_posix()]
    manifest=OUT/'manifest.json'
    manifest.write_text(json.dumps({'files_sha256':files,'source_directory':'outputs/rk3568-usb-device-20261006','excluded':['__pycache__']},indent=2)+'\n',newline='\n')
    receipt={'status':'LINUX_ONLY_USB2_PERIPHERAL_OFFLINE_DT_CANDIDATE',
        'manifest_sha256':sha(manifest),'files':len(files),'baseline_sha256':C.BASE_SHA,
        'candidate_sha256':result['candidate_sha256'],'candidate_bytes':163303,'real_libfdt_identical_runs':3,
        'full_tree_nodes':962,'full_tree_properties':4887,'phandles':762,'whitelisted_properties_changed':7,
        'usb_dependency_closed_nodes':39,'actual_binary_negatives_rejected':29,'native_semantic_negatives_rejected':22,
        'dtc_runs_exit0':4,'decode_diagnostics_exact_after_path_normalization':True,
        'encode_only_one_exact_old_usb3_warning_removed':True,'new_or_changed_diagnostics':0,
        'encode_strict_diagnostics_equality':False,'removed_warning':result['removed_warning'],
        'failed_strict_v1_retained':True,'input_snapshot_files':17,
        'candidate_path':'build/usb2-peripheral-v2/usb2-peripheral-1.dtb',
        'limits':result['limits'],'otg_vbus_supply_absent':True,'otg_phy_supply_absent':True,
        'absence_is_only_dt_description_not_physical_proof':True,'kernel_or_phy_model_built':False,
        'accepted_for_board':False,'board_tested':False,'usb_recovery_verified':False,
        'physical_no_vbus_verified':False,'shared_uboot_tree_approved':False,'audio_package_modified':False,
        'kernel_config_modified':False,'hardware_or_network_access':False,
    }
    record=OUT/'receipt.json'
    record.write_text(json.dumps(receipt,indent=2)+'\n',newline='\n')
    for rel,expected in files.items():
        assert sha(OUT/rel)==expected
    print(json.dumps({'receipt':str(record),'receipt_sha256':sha(record),'manifest_sha256':sha(manifest),'files':len(files),'candidate_sha256':result['candidate_sha256']}))

if __name__=='__main__':
    main()
