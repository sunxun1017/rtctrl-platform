#!/usr/bin/env python3
"""Verify complete DT semantics and existing DTC diagnostics independently."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PACKAGE=ROOT/'outputs/rk3568-boot-package-20261005'
BASE=ROOT/'outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb'
DTC=ROOT/'.deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc'
spec=importlib.util.spec_from_file_location('semantics',PACKAGE/'dt-semantics-v2.py')
semantic=importlib.util.module_from_spec(spec)
spec.loader.exec_module(semantic)
before=semantic.parse(BASE.read_bytes())
target=HERE/'build/dtb-v2/audio-battery-1.dtb'
after=semantic.parse(target.read_bytes())
props=json.loads((HERE/'build/dtb-v2/original-properties.json').read_text())
node=props['node']
expected=dict(before['properties'])
expected.update({node+':'+key:value for key,value in props['properties_hex'].items()})
checks={'one_node_added':set(after['nodes'])==set(before['nodes'])|{node},
    'all_other_properties_equal':after['properties']==expected,
    'all_16_original_properties_equal':len(props['properties_hex'])==16,
    'phandles_equal':semantic.phandles(before)==semantic.phandles(after)}
for key in ['reservations','boot_cpuid','version','last_compatible_version']:
    checks[key+'_equal']=before[key]==after[key]
result=subprocess.run([str(DTC),'-I','dtb','-O','dts',str(BASE)],capture_output=True)
(HERE/'build/dtb-v2/baseline-dtc-stderr.txt').write_bytes(result.stderr)
checks['baseline_dtc_exit0']=result.returncode==0
checks['exact_existing_warnings_equal']=result.stderr==(HERE/'build/dtb-v2/dtc-stderr.txt').read_bytes()
report={'checks':checks,'passed':all(checks.values()),'candidate_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
    'base_nodes':len(before['nodes']),'candidate_nodes':len(after['nodes']),'baseline_warnings':len(result.stderr),
    'board_tested':False,'new_battery_calibrated':False}
(HERE/'build/dtb-v2/verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
if not report['passed']:
    raise ValueError('DT verification failed')
