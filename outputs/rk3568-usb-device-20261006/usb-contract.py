#!/usr/bin/env python3
"""Full-tree seven-property contract and genuine provider-cell dependency audit."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

HERE=Path(__file__).resolve().parent
INPUTS=HERE/'inputs-v1'
DRD='/usbdrd'
DWC=DRD+'/dwc3@fcc00000'
OTG='/usb2-phy@fe8a0000/otg-port'
BASE_SHA='4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f'

def require(condition,message):
    if not condition:
        raise ValueError(message)

def sha(blob):
    return hashlib.sha256(blob).hexdigest()

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
    return obj

SEM=module('usb_complete_semantic',INPUTS/'dt-semantics-v2.py')

def inputs():
    record=json.loads((INPUTS/'manifest.json').read_text())
    for rel,item in record['files'].items():
        require(sha((INPUTS/rel).read_bytes())==item['sha256'],'Input changed: '+rel)
    blob=(INPUTS/'audio-linux-tested.dtb').read_bytes()
    require(sha(blob)==BASE_SHA and len(blob)==163285,'Exact tested Linux DT required')
    return blob

def expected(before):
    handles=SEM.phandles(before)
    found=[handle for handle,node in handles.items() if node==OTG]
    require(len(found)==1,'Unique current-tree OTG phandle required')
    require(before['properties'][OTG+':#phy-cells']=='00000000','OTG provider #phy-cells must be zero')
    for name in ('vbus-supply','phy-supply'):
        require(OTG+':'+name not in before['properties'],'Baseline OTG supply unexpectedly present')
    return {DRD+':status':b'okay\0'.hex(),DWC+':status':b'okay\0'.hex(),OTG+':status':b'okay\0'.hex(),
        DWC+':dr_mode':b'peripheral\0'.hex(),DWC+':maximum-speed':b'high-speed\0'.hex(),
        DWC+':phys':struct.pack('>I',found[0]).hex(),DWC+':phy-names':b'usb2-phy\0'.hex()}

def audit_tree(before,after):
    want=expected(before)
    changed=SEM.diff(before,after)
    allowed={key:{'before':before['properties'].get(key),'after':value} for key,value in want.items()}
    require(changed==allowed,'Full tree must have exactly the seven whitelisted property changes')
    require(SEM.phandles(before)==SEM.phandles(after),'Every phandle must remain identical')
    for key,value in want.items():
        require(after['properties'].get(key)==value,'USB2/peripheral contract: '+key)
    for name in ('vbus-supply','phy-supply'):
        require(OTG+':'+name not in after['properties'],'OTG supply must stay absent')
    return {'full_diff':changed,'nodes':len(after['nodes']),'properties':len(after['properties']),
        'phandles':len(SEM.phandles(after)),'only_whitelist_changed':True,'otg_supplies_absent_as_dt_properties':True}

def audit(blob):
    baseline=inputs()
    before,after=SEM.parse(baseline),SEM.parse(blob)
    result=audit_tree(before,after)
    # Reuse reviewed bounded USB graph logic without running or modifying its old main/output.
    prior=module('usb_prior_closure',INPUTS/'prior/audit-usb-closure.py')
    prior.PACKAGE=INPUTS
    graph=prior.closure(blob)
    phy_edges=[item for item in graph['nodes'][DWC]['dependencies'] if item['property']=='phys']
    require(phy_edges==[{'property':'phys','provider':OTG,'args':[]}],'Exactly the real OTG USB2 provider required')
    for path in (DRD,DWC,OTG,'/usb2-phy@fe8a0000'):
        require(graph['nodes'][path]['effective_available_by_status'],'Required path/ancestor disabled: '+path)
    result.update({'dependency_graph':graph,'graph_references_resolved':True,
        'device_tree_only_not_driver_probe_success':True,'linux_only_candidate':True,
        'shared_uboot_tree_approved':False,'board_tested':False,'usb_recovery_verified':False,'physical_no_vbus_verified':False})
    return result
