#!/usr/bin/env python3
"""Linux real-libfdt/DTC build, full contract audit, and binary negative fixtures."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('usb_contract_build',HERE/'usb-contract.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)

def write_json(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n',newline='\n')

def mutate(real,data,path,name,value):
    opened=real.opened(data)
    real.set_property(opened,path,name,value)
    return real.packed(opened)

def negatives(real,candidate,out):
    values=[
        ('missing_usb2_phys',C.DWC,'phys',b''),
        ('wrong_phy',C.DWC,'phys',struct.pack('>I',0x24)),
        ('unknown_phy',C.DWC,'phys',struct.pack('>I',0xffffffff)),
        ('old_dual_phy',C.DWC,'phys',bytes.fromhex('000000280000002400000004')),
        ('extra_phy_argument',C.DWC,'phys',bytes.fromhex('0000002800000004')),
        ('unterminated_phy_name',C.DWC,'phy-names',b'usb2-phy'),
        ('extra_usb3_name',C.DWC,'phy-names',b'usb2-phy\0usb3-phy\0'),
        ('host_role',C.DWC,'dr_mode',b'host\0'),
        ('otg_role',C.DWC,'dr_mode',b'otg\0'),
        ('super_speed',C.DWC,'maximum-speed',b'super-speed\0'),
        ('drd_disabled',C.DRD,'status',b'disabled\0'),
        ('dwc_disabled',C.DWC,'status',b'disabled\0'),
        ('otg_phy_disabled',C.OTG,'status',b'disabled\0'),
        ('combphy_enabled','/phy@fe820000','status',b'okay\0'),
        ('host_enabled','/usbhost','status',b'okay\0'),
        ('other_phy_enabled','/usb2-phy@fe8b0000/otg-port','status',b'okay\0'),
        ('vbus_supply_added',C.OTG,'vbus-supply',struct.pack('>I',0x2fa)),
        ('phy_supply_added',C.OTG,'phy-supply',struct.pack('>I',0x2fa)),
        ('clock_changed',C.DRD,'clocks',struct.pack('>I',0xffffffff)),
        ('reset_changed',C.DWC,'resets',struct.pack('>I',0xffffffff)),
        ('phandle_changed',C.OTG,'phandle',struct.pack('>I',0x2fa)),
        ('chosen_changed','/chosen','bootargs',b'changed\0'),
        ('gpio_added',C.OTG,'enable-gpios',struct.pack('>II',0x23,1)),
        ('provider_phy_cells_changed',C.OTG,'#phy-cells',struct.pack('>I',1)),
    ]
    cases=[('original_without_usb_device_changes',C.inputs())]
    cases.extend((label,mutate(real,candidate,path,name,value)) for label,path,name,value in values)
    reserved=bytearray(candidate)
    reserve_offset=struct.unpack_from('>I',reserved,16)[0]
    struct.pack_into('>Q',reserved,reserve_offset,struct.unpack_from('>Q',reserved,reserve_offset)[0]+8)
    cases.extend([('reservation_changed',bytes(reserved)),('bad_magic',b'BAD!'+candidate[4:]),
                  ('truncated',candidate[:-1]),('extra_tail',candidate+b'\0')])
    out.mkdir()
    results=[]
    for label,blob in cases:
        (out/(label+'.dtb')).write_bytes(blob)
        try:
            C.audit(blob)
        except (ValueError,KeyError,UnicodeError,struct.error) as error:
            results.append({'name':label,'rejected':True,'reason':str(error),'sha256':C.sha(blob),'bytes':len(blob)})
        else:
            results.append({'name':label,'rejected':False})
    C.require(all(item['rejected'] for item in results),'Binary negative fixture unexpectedly passed')
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',default='usb2-peripheral-v2')
    args=parser.parse_args()
    C.require(os.name=='posix','Real libfdt/DTC execution requires Linux; preparation is separate')
    C.require(re.fullmatch('[a-z0-9-]+',args.name),'Fresh output name must be a basename')
    out=HERE/'build'/args.name
    C.require(out.resolve()==out,'Ordinary own output required')
    out.mkdir(parents=True,exist_ok=False)
    try:
        baseline=C.inputs()
        before=C.SEM.parse(baseline)
        try:
            C.audit(baseline)
        except ValueError as error:
            original_red={'rejected':True,'reason':str(error),'baseline_sha256':C.sha(baseline)}
        else:
            raise ValueError('Original disabled tree must fail USB2/peripheral contract')
        write_json(out/'original-red.json',original_red)
        real_module=C.module('usb_locked_libfdt',C.INPUTS/'libfdt-v2.py')
        real=real_module.RealLibFdt()
        runs=[]
        for number in range(1,4):
            opened=real.opened(baseline)
            for key,value in C.expected(before).items():
                path,name=key.rsplit(':',1)
                real.set_property(opened,path,name,bytes.fromhex(value))
            candidate=real.packed(opened)
            audit=C.audit(candidate)
            (out/f'usb2-peripheral-{number}.dtb').write_bytes(candidate)
            runs.append({'number':number,'sha256':C.sha(candidate),'bytes':len(candidate)})
        C.require(len({item['sha256'] for item in runs})==1,'Real libfdt build not deterministic')
        (out/'audio-linux-baseline.dtb').write_bytes(baseline)
        write_json(out/'usb-dependency-graph.json',audit.pop('dependency_graph'))
        write_json(out/'full-tree-audit.json',audit)
        dtc=C.INPUTS/'dtc'
        dtc.chmod(0o755)  # Only the new copied tool, never an existing tool/tree.
        dtc_out=out/'dtc';dtc_out.mkdir()
        executed=[];diagnostics={}
        for label,path in [('baseline',out/'audio-linux-baseline.dtb'),('candidate',out/'usb2-peripheral-1.dtb')]:
            for stage,fmt,target in [('decode','dtb','dts'),('encode','dts','dtb')]:
                if stage=='encode':
                    path=dtc_out/(label+'.dts')
                argv=[str(dtc),'-I',fmt,'-O',target,str(path)]
                proc=subprocess.run(argv,capture_output=True,timeout=30)
                stem=dtc_out/(label+'-'+stage)
                stem.with_suffix('.stdout').write_bytes(proc.stdout)
                stem.with_suffix('.stderr').write_bytes(proc.stderr)
                executed.append({'stage':label+'-'+stage,'argv':argv,'exit_code':proc.returncode,
                    'stdout_sha256':C.sha(proc.stdout),'stderr_sha256':C.sha(proc.stderr),'warning_bytes':len(proc.stderr)})
                write_json(out/'dtc-runs.json',executed)
                C.require(proc.returncode==0,'Actual DTC rejected '+label+'-'+stage)
                normalized=proc.stderr.replace(str(path).encode(),b'<input>')
                if stage=='encode':
                    # Added maximum-speed shifts source lines: retain warning class/node/message,
                    # normalize only source path and line/column ranges, never diagnostic contents.
                    normalized=re.sub(rb'<input>:[0-9]+\.[0-9]+(?:-[0-9]+(?:\.[0-9]+)?)?:',b'<input>:<location>:',normalized)
                    rebuilt=proc.stdout
                    (dtc_out/(label+'-roundtrip.dtb')).write_bytes(rebuilt)
                    C.require(C.SEM.parse(rebuilt)==C.SEM.parse((out/('audio-linux-baseline.dtb' if label=='baseline' else 'usb2-peripheral-1.dtb')).read_bytes()),'DTC changed full semantics')
                else:
                    (dtc_out/(label+'.dts')).write_bytes(proc.stdout)
                diagnostics[label+'-'+stage]=normalized
                (dtc_out/(label+'-'+stage+'-normalized.stderr')).write_bytes(normalized)
        C.require(diagnostics['baseline-decode']==diagnostics['candidate-decode'],
                  'DTC decode diagnostics must stay byte-identical after path normalization')
        removed_warning = b'<input>:<location>: Warning (phys_property): /usbdrd/dwc3@fcc00000:phys: cell 1 is not a phandle reference\n'
        old_encode = diagnostics['baseline-encode']
        new_encode = diagnostics['candidate-encode']
        C.require(old_encode.count(removed_warning)==1,
                  'Exactly one known old USB3 numeric-reference warning must be present')
        C.require(old_encode.replace(removed_warning,b'',1)==new_encode,
                  'Only the exact removed USB3 numeric-reference warning may disappear; no added/reordered/changed messages')
        rejected=negatives(real,candidate,out/'rejected-dtbs')
        result={'status':'LINUX_ONLY_USB2_PERIPHERAL_OFFLINE_CANDIDATE',
            'baseline_sha256':C.sha(baseline),'candidate_sha256':C.sha(candidate),'real_libfdt_sha256':real_module.LIB_SHA,
            'dtc_sha256':C.sha(dtc.read_bytes()),'real_libfdt_runs':runs,'full_tree_audit':audit,
            'dtc_runs':executed,'dtc_decode_diagnostics_same_after_path_normalization':True,
            'dtc_encode_diagnostics_same_after_path_and_location_normalization':False,
            'dtc_encode_only_expected_warning_removed':True,'dtc_encode_new_or_changed_messages':0,
            'removed_warning':removed_warning.decode().rstrip(),
            'diagnostics_normalization_scope':'Decode source path only; encode source path and line/column ranges only. Warning categories/node paths/messages retained.',
            'negative_binary_fixtures':rejected,'script_sha256':C.sha(Path(__file__).read_bytes()),
            'contract_sha256':C.sha((HERE/'usb-contract.py').read_bytes()),'inputs_manifest_sha256':C.sha((C.INPUTS/'manifest.json').read_bytes()),
            'kernel_or_phy_model_built':False,'board_tested':False,'usb_recovery_verified':False,
            'physical_no_vbus_verified':False,'shared_uboot_tree_approved':False,'accepted_for_board':False,
            'limits':['DWC3 may accept missing USB2/USB3 PHY as NULL; UDC presence alone does not prove PHY.','DT absent supply does not prove no physical VBUS; PHY probe/ID/resume/regulator fallback can still turn it on.','DMO pin identity remains unknown.','Linux-only overlay-applied tree, not shared U-Boot recovery/flash tree or deployment permission.']}
        write_json(out/'result.json',result)
        print(json.dumps({'candidate_sha256':C.sha(candidate),'candidate_bytes':len(candidate),'binary_negatives_rejected':len(rejected),'decode_diagnostics_same':True,'encode_only_expected_warning_removed':True}))
    except Exception as error:
        write_json(out/'failed.json',{'error':repr(error),'success':False,'board_tested':False})
        raise

if __name__=='__main__':
    main()
