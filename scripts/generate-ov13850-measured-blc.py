#!/usr/bin/env python3
"""Generate an experimental OV13850 ISP35 IQ using reviewed dark measurements.
No vendor IQ is bundled. Scale 4 is supported by the documented board probe;
this script does not establish calibration validity for another sensor/mode.
"""
import argparse, copy, hashlib, json, math
from pathlib import Path

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def interpolate(x, xs, ys):
    if x <= xs[0]: return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x-xs[i-1])/(xs[i]-xs[i-1])
            return ys[i-1]*(1-t)+ys[i]*t
    return ys[-1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--iq',type=Path,required=True)
    p.add_argument('--measurements',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ae-factor',type=float,default=1.5)
    a=p.parse_args()
    if a.output.exists(): raise ValueError('output must not exist')
    if not 1 <= a.ae_factor <= 1.5: raise ValueError('AE factor outside reviewed range')
    rows=json.loads(a.measurements.read_text(encoding='utf8'))
    if [r['gain_reg'] for r in rows] != [16,32,64,128,248]: raise ValueError('expected five reviewed gain measurements')
    for r in rows:
        if len(r['R_Gr_Gb_B'])!=4 or not all(math.isfinite(v) and 0<v<32 for v in r['R_Gr_Gb_B']): raise ValueError('invalid measured black level')
        if r['tile_mean_range'][1]-r['tile_mean_range'][0]>1: raise ValueError('dark field spatial variation requires review')
    d=json.loads(a.iq.read_text(encoding='utf8'));before=copy.deepcopy(d)
    if d['sensor_calib']['iso_list'] != [50*2**i for i in range(13)]: raise ValueError('unreviewed ISO grid')
    scenes=[s for m in d['main_scene'] for s in m['sub_scene']]
    if len(scenes)!=1: raise ValueError('only reviewed single scene supported')
    s=scenes[0]['scene_isp35'];b=s['blc'];b['en']=1
    b['stAuto']['sta']['autoBlc']['sw_blcT_autoBlc_en']=0
    if len(b['stAuto']['dyn'])!=13: raise ValueError('unexpected BLC table')
    keys=['hw_blcC_obR_val','hw_blcC_obGr_val','hw_blcC_obGb_val','hw_blcC_obB_val']
    for iso,row in zip(d['sensor_calib']['iso_list'],b['stAuto']['dyn']):
        row['obcPreTnr']={key:round(4*interpolate(iso/50*16,[r['gain_reg'] for r in rows],[r['R_Gr_Gb_B'][c] for r in rows])) for c,key in enumerate(keys)}
        row['obcPostTnr']['sw_blcT_obcPostTnr_en']=0
        row['obcPostTnr']['sw_blcT_autoOB_offset']=0
    target=s['ae_calib']['linAeCtrl']['dynSetpoint']
    target['sw_aeT_dynSetpoint_dot']=[v*a.ae_factor for v in target['sw_aeT_dynSetpoint_dot']]
    if not all(0<=v<=255 for v in target['sw_aeT_dynSetpoint_dot']): raise ValueError('AE out of bounds')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_bytes((json.dumps(d,indent=2)+'\n').encode())
    report={'status':'EXPERIMENTAL_CURRENT_MODE_TEMPERATURE','input_sha256':sha(a.iq),'measurements_sha256':sha(a.measurements),'output_sha256':sha(a.output),'ae_factor':a.ae_factor,'raw_to_isp_scale':4,'limits':['not CCM/AWB/LSC/noise calibration','ISO beyond measured range clamps endpoint and must remain unreachable with reviewed AE route','black-level scale requires documented runtime probe','no full temperature or exposure sweep']}
    a.output.with_suffix('.provenance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
