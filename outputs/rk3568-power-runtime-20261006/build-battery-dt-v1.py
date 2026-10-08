#!/usr/bin/env python3
"""Copy only the original battery node using the locked real libfdt."""
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PACKAGE=ROOT/'outputs/rk3568-boot-package-20261005'
BATTERY='/i2c@fdd40000/pmic@20/battery'
BASE=ROOT/'outputs/rk3568-audio-20261005/build/dtb-v3/audio.dtb'
DTC=ROOT/'.deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def load(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),PACKAGE/name)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def main():
    if sha(BASE.read_bytes())!='9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478':
        raise ValueError('Baseline audio DT changed')
    locks={
        'dt-semantics-v2.py':'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56',
        'libfdt-v2.py':'9fdba61ae8d7d004ac7f24b7f116f6a314032c01624357f01619f609a5b8a954'}
    for name,expected in locks.items():
        if sha((PACKAGE/name).read_bytes())!=expected:
            raise ValueError('DT tool changed')
    semantic=load('dt-semantics-v2.py')
    lib=load('libfdt-v2.py').RealLibFdt()
    original=semantic.parse((HERE/'original-v1/android-original.dtb').read_bytes())
    before=semantic.parse(BASE.read_bytes())
    properties={key.split(':',1)[1]:bytes.fromhex(value) for key,value in original['properties'].items() if key.split(':',1)[0]==BATTERY}
    if len(properties)!=16 or properties['compatible']!=b'rk817,battery\0' or BATTERY in before['nodes']:
        raise ValueError('Exact original battery node/absent baseline required')
    if 'phandle' in properties or 'linux,phandle' in properties:
        raise ValueError('Unexpected original battery phandle requires separate review')
    output=HERE/'build/dtb-v2'
    output.mkdir(parents=True,exist_ok=False)
    lib.lib.fdt_add_subnode.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_char_p]
    lib.lib.fdt_add_subnode.restype=ctypes.c_int
    runs=[]
    for number in range(1,4):
        opened=lib.opened(BASE.read_bytes())
        status=lib.lib.fdt_add_subnode(opened,lib.node(opened,BATTERY.rsplit('/',1)[0]),b'battery')
        if status<0:
            raise ValueError('fdt_add_subnode failed '+str(status))
        for key,value in properties.items():
            lib.set_property(opened,BATTERY,key,value)
        candidate=lib.packed(opened)
        after=semantic.parse(candidate)
        expected=dict(before['properties'])
        expected.update({BATTERY+':'+key:value.hex() for key,value in properties.items()})
        if after['properties']!=expected or [node for node in after['nodes'] if node!=BATTERY]!=before['nodes']:
            raise ValueError('Complete DT semantics exceed one node/16 properties')
        if semantic.phandles(before)!=semantic.phandles(after) or before['reservations']!=after['reservations']:
            raise ValueError('Phandles/reservations changed')
        (output/f'audio-battery-{number}.dtb').write_bytes(candidate)
        runs.append({'number':number,'bytes':len(candidate),'sha256':sha(candidate),'checks':20})
    if len({run['sha256'] for run in runs})!=1:
        raise ValueError('Real libfdt copies are not deterministic')
    decoded={}
    for key,value in properties.items():
        decoded[key]=value.hex() if key=='compatible' else list(struct.unpack('>'+'I'*(len(value)//4),value))
    (output/'original-properties.json').write_text(json.dumps({'node':BATTERY,'properties_hex':{key:value.hex() for key,value in properties.items()},'decoded':decoded},indent=2)+'\n')
    result=subprocess.run([str(DTC),'-I','dtb','-O','dts',str(output/'audio-battery-1.dtb')],capture_output=True)
    (output/'candidate.dts').write_bytes(result.stdout)
    (output/'dtc-stderr.txt').write_bytes(result.stderr)
    result.check_returncode()
    report={'baseline_sha256':sha(BASE.read_bytes()),'original_sha256':sha((HERE/'original-v1/android-original.dtb').read_bytes()),
        'candidate_sha256':runs[0]['sha256'],'real_libfdt_sha256':load('libfdt-v2.py').LIB_SHA,'dtc_sha256':sha(DTC.read_bytes()),
        'runs':runs,'all_properties_exact_original':True,'only_battery_node_added':True,'properties':16,
        'no_charger_BQ_FUSB_nodes_added':True,'board_tested':False,'new_battery_calibrated':False,
        'design_capacity_mAh':decoded['design_capacity'][0],'design_qmax_mAh':decoded['design_qmax'][0],
        'dtc_exit_code':result.returncode,'dtc_warning_bytes':len(result.stderr)}
    (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':
    main()
