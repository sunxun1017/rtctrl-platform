#!/usr/bin/env python3
"""Estimate current-light manual WB from 3-frame low-aligned BG10 exposure series.
Not AWB calibration. Requires numpy. Does not enable unmeasured BLC.
"""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--iq',type=Path,required=True)
p.add_argument('--raw-dir',type=Path,required=True)
p.add_argument('--out-dir',type=Path,required=True)
a=p.parse_args()
a.out_dir.mkdir(parents=True,exist_ok=True)
out=a.out_dir/'ov13850_ATK-MCOV13850_default.json'
if out.exists(): raise FileExistsError(out)
rows=[]; inputs=[]
for e in [192,768,1536]:
 f=a.raw_dir/f'reset-{e}.raw'
 raw=np.fromfile(f,dtype='<u2').reshape(3,1568,2112)
 if raw.max()>1023: raise ValueError('expected low-aligned 10bit RAW')
 roi=raw[:,500:900,800:1200]
 rows.append([roi[:,1::2,1::2].mean(),roi[:,1::2,0::2].mean(),roi[:,0::2,1::2].mean(),roi[:,0::2,0::2].mean()])
 inputs.append({'file':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
slope,offset=np.polyfit([192,768,1536],rows,1)
if np.any(slope<=0): raise ValueError('nonpositive response')
g=slope[1:3].mean(); gains=[float(g/slope[0]),1.,1.,float(g/slope[3])]
if not all(1<=v<=4 for v in gains): raise ValueError('unexpected gains; review data')
d=json.loads(a.iq.read_text())
s=d['main_scene'][0]['sub_scene'][0]['scene_isp35']
s['wb']['wbGainCtrl']['opMode']='RK_AIQ_OP_MODE_MANUAL'
s['wb']['wbGainCtrl']['manualPara']['mode']='mwb_mode_wbgain'
s['wb']['wbGainCtrl']['manualPara']['cfg']['manual_wbgain']=gains
out.write_text(json.dumps(d,indent=2)+'\n',encoding='utf8')
report={'status':'CURRENT_LIGHT_MANUAL_WB_NOT_AWB_CALIBRATION','roi_xywh':[800,500,400,400],'channel_order':['R','Gr','Gb','B'],'exposures':[192,768,1536],'analog_gain_register':16,'means':rows,'slopes':slope.tolist(),'intercepts_not_blc':offset.tolist(),'manual_wb':gains,'inputs':inputs,'input_iq_sha256':hashlib.sha256(a.iq.read_bytes()).hexdigest(),'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'limitations':['ordinary white paper under current light only','BLC remains disabled; intercept is not dark calibration','foreign CCM/LSC remain disabled','not portable across light sources']}
(a.out_dir/'measured-wb-provenance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps(report,indent=2))
