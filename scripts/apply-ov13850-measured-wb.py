#!/usr/bin/env python3
"""Reproduce the measured manual-WB candidate from its exact base IQ and provenance."""
import argparse,json,hashlib,math
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--base',type=Path,required=True)
p.add_argument('--measurement',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
m=json.loads(a.measurement.read_text())
if hashlib.sha256(a.base.read_bytes()).hexdigest()!=m['input_iq_sha256']: raise SystemExit('Base hash mismatch; regenerate measurement for this input')
g=m['manual_wb']
if len(g)!=4 or not all(math.isfinite(x) and 1<=x<=4 for x in g): raise SystemExit('Invalid gains')
d=json.loads(a.base.read_text()); w=d['main_scene'][0]['sub_scene'][0]['scene_isp35']['wb']['wbGainCtrl']
w['opMode']='RK_AIQ_OP_MODE_MANUAL';w['manualPara']['mode']='mwb_mode_wbgain';w['manualPara']['cfg']['manual_wbgain']=g
payload=(json.dumps(d,indent=2)+'\n').encode()
# Historical Windows measurements used CRLF; verify either exact encoding.
if hashlib.sha256(payload).hexdigest()!=m['output_sha256']: payload=payload.replace(b'\n',b'\r\n')
if hashlib.sha256(payload).hexdigest()!=m['output_sha256']: raise SystemExit('Output hash mismatch')
with a.output.open('xb') as f:f.write(payload)
print('Exact candidate reproduced; current-light manual WB only')
