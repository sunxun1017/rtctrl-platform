#!/usr/bin/env python3
"""Preserve the actual DTC discrepancy instead of claiming strict equality."""
from collections import Counter
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('usb_diagnostics_contract',HERE/'usb-contract.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)
build=HERE/'build/usb2-peripheral-v1'
runs=json.loads((build/'dtc-runs.json').read_text())
assert len(runs)==4
for run in runs:
    stem=build/'dtc'/run['stage']
    assert C.sha(stem.with_suffix('.stdout').read_bytes())==run['stdout_sha256']
    assert C.sha(stem.with_suffix('.stderr').read_bytes())==run['stderr_sha256']
    assert run['exit_code']==0
stage={name:(build/'dtc'/(name+'-normalized.stderr')).read_bytes() for name in ('baseline-decode','candidate-decode','baseline-encode','candidate-encode')}
before=Counter(stage['baseline-encode'].splitlines())
after=Counter(stage['candidate-encode'].splitlines())
removed=list((before-after).elements());added=list((after-before).elements())
expected=b'<input>:<location>: Warning (phys_property): /usbdrd/dwc3@fcc00000:phys: cell 1 is not a phandle reference'
report={'all_four_dtc_exit0':True,'decode_exact_after_path_normalization':stage['baseline-decode']==stage['candidate-decode'],
    'encode_exact_after_path_and_location_normalization':stage['baseline-encode']==stage['candidate-encode'],
    'removed_messages':[line.decode() for line in removed],'added_messages':[line.decode() for line in added],
    'only_removed_usb3_numeric_reference_warning':removed==[expected] and not added,
    'strict_encode_equality_gate_passed':False,'evidence_only_not_board_permission':True,
    'warning_categories_and_messages_not_filtered':True,'board_tested':False}
out=HERE/'build/diagnostics-difference-v1';out.mkdir(parents=True,exist_ok=False)
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n',newline='\n')
print(json.dumps(report))
