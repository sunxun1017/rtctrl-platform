#!/usr/bin/env python3
"""Keep strict failed v1 and create the explicitly authorized diagnostic gate v2."""
from pathlib import Path

HERE=Path(__file__).resolve().parent
old=(HERE/'build-candidate.py').read_text()
before='''        for stage in ('decode','encode'):
            C.require(diagnostics['baseline-'+stage]==diagnostics['candidate-'+stage],'DTC diagnostic contents changed: '+stage)
'''
after='''        C.require(diagnostics['baseline-decode']==diagnostics['candidate-decode'],
                  'DTC decode diagnostics must stay byte-identical after path normalization')
        removed_warning = b'<input>:<location>: Warning (phys_property): /usbdrd/dwc3@fcc00000:phys: cell 1 is not a phandle reference\\n'
        old_encode = diagnostics['baseline-encode']
        new_encode = diagnostics['candidate-encode']
        C.require(old_encode.count(removed_warning)==1,
                  'Exactly one known old USB3 numeric-reference warning must be present')
        C.require(old_encode.replace(removed_warning,b'',1)==new_encode,
                  'Only the exact removed USB3 numeric-reference warning may disappear; no added/reordered/changed messages')
'''
assert old.count(before)==1
new=old.replace(before,after,1)
new=new.replace("default='usb2-peripheral-v1'","default='usb2-peripheral-v2'",1)
new=new.replace("'dtc_encode_diagnostics_same_after_path_and_location_normalization':True,",
    "'dtc_encode_diagnostics_same_after_path_and_location_normalization':False,\n            'dtc_encode_only_expected_warning_removed':True,'dtc_encode_new_or_changed_messages':0,\n            'removed_warning':removed_warning.decode().rstrip(),")
new=new.replace("'decode_and_encode_diagnostics_same':True", "'decode_diagnostics_same':True,'encode_only_expected_warning_removed':True")
target=HERE/'build-candidate-v2.py'
assert not target.exists()
target.write_text(new,newline='\n')
print('v1 unchanged; prepared explicitly authorized precise diagnostic-removal gate v2')
