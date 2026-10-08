#!/usr/bin/env python3
"""Execute semantic fixture negatives on Windows; no DTB generation or DTC claim."""
import copy
import json
from pathlib import Path
import struct
import importlib.util

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('usb_contract_native',HERE/'usb-contract.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)
before=C.SEM.parse(C.inputs())
planned=copy.deepcopy(before)
planned['properties'].update(C.expected(before))
positive=C.audit_tree(before,planned)
cases=[]

def prop(label,key,value):
    tree=copy.deepcopy(planned)
    if value is None:
        tree['properties'].pop(key,None)
    else:
        tree['properties'][key]=value.hex()
    cases.append((label,tree))

cases.append(('original_tested_tree_without_usb_device_changes',before))
prop('missing_usb2_phys',C.DWC+':phys',None)
prop('wrong_current_tree_phy',C.DWC+':phys',struct.pack('>I',0x24))
prop('old_dual_phy_phys',C.DWC+':phys',bytes.fromhex(before['properties'][C.DWC+':phys']))
prop('usb2_name_not_nul',C.DWC+':phy-names',b'usb2-phy')
prop('extra_usb3_name',C.DWC+':phy-names',b'usb2-phy\0usb3-phy\0')
prop('host_role',C.DWC+':dr_mode',b'host\0')
prop('otg_role',C.DWC+':dr_mode',b'otg\0')
prop('super_speed',C.DWC+':maximum-speed',b'super-speed\0')
prop('combphy0_enabled','/phy@fe820000:status',b'okay\0')
prop('host_enabled','/usbhost:status',b'okay\0')
prop('other_phy_enabled','/usb2-phy@fe8b0000/otg-port:status',b'okay\0')
prop('new_vbus_supply',C.OTG+':vbus-supply',struct.pack('>I',0x2fa))
prop('new_phy_supply',C.OTG+':phy-supply',struct.pack('>I',0x2fa))
prop('clock_changed',C.DRD+':clocks',struct.pack('>I',0xffffffff))
prop('reset_changed',C.DWC+':resets',struct.pack('>I',0xffffffff))
prop('phandle_changed',C.OTG+':phandle',struct.pack('>I',0x2fa))
prop('chosen_changed','/chosen:bootargs',b'changed\0')
prop('new_gpio',C.OTG+':enable-gpios',struct.pack('>II',0x23,1))
tree=copy.deepcopy(planned);tree['reservations'][0][0]+=8;cases.append(('reservation_changed',tree))
tree=copy.deepcopy(planned);tree['boot_cpuid']+=1;cases.append(('boot_cpu_changed',tree))
tree=copy.deepcopy(planned);tree['nodes'].append('/unexpected-usb-test');cases.append(('new_node',tree))
results=[]
for label,tree in cases:
    try:
        C.audit_tree(before,tree)
    except (ValueError,KeyError) as error:
        results.append({'name':label,'rejected':True,'reason':str(error)})
    else:
        results.append({'name':label,'rejected':False})
C.require(all(item['rejected'] for item in results),'Semantic bad fixture passed')
out=HERE/'build/native-plan-v1';out.mkdir(parents=True,exist_ok=False)
(out/'planned-semantic-fixture.json').write_text(json.dumps(planned,indent=2)+'\n',newline='\n')
report={'baseline_sha256':C.BASE_SHA,'positive_semantic_fixture_passed':True,'negative_fixtures':results,
    'positive':positive,'native_execution':True,'dtb_generated':False,'linux_libfdt_executed':False,'dtc_executed':False,
    'board_tested':False,'physical_no_vbus_verified':False}
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n',newline='\n')
print(json.dumps({'positive_semantic_fixture':True,'rejected_semantic_fixtures':len(results),'dtb_generated':False}))
