#!/usr/bin/env python3
"""Official-guide all-pixel AWB diagnostic; NOT production calibration."""
import argparse,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--base',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--all-pixels',action='store_true')
a=p.parse_args();d=json.loads(a.base.read_text());w=d['main_scene'][0]['sub_scene'][0]['scene_isp35']['wb'];changes={}
def put(obj,k,v,path):
 changes[path+k]={'before':obj[k],'after':v};obj[k]=v
put(w['wbGainCtrl'],'opMode','RK_AIQ_OP_MODE_AUTO','wbGainCtrl/')
step=w['awbGnCalcStep'];stat=w['awbStats']
put(step['wbGainAdjust'],'awbGnAdjst_en',0,'awbGnCalcStep/wbGainAdjust/')
put(step['wbGainOffset'],'offset_en',0,'awbGnCalcStep/wbGainOffset/')
put(step['wbGnType1']['sgc'],'sgc_en',0,'awbGnCalcStep/wbGnType1/sgc/')
if a.all_pixels:
 for k in ['hw_awbCfg_uvDct_en','hw_awbCfg_xyDct_en','hw_awbCfg_rotYuvDct_en']:
  if k in stat: put(stat,k,0,'awbStats/')
 for k in ['sw_awbCfg_lgtPrefer_en','sw_awbCfg_lgtSrcWgt_en']:
  put(stat,k,0,'awbStats/')
with a.output.open('x',encoding='utf8',newline='\n') as f:json.dump(d,f,indent=2);f.write('\n')
r={'status':'DIAGNOSTIC_NOT_PRODUCTION','all_pixels':a.all_pixels,'source':'SDK Color Optimization Guide ISP39/33/35 section 2.2.2.9.1','input_sha256':hashlib.sha256(a.base.read_bytes()).hexdigest(),'output_sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),'changes':changes,'limitations':['foreign reference illuminants and fallback remain','all-pixel estimate can be biased by colored objects','not evaluated until runtime strategy and image capture succeed']}
a.output.with_suffix('.provenance.json').write_text(json.dumps(r,indent=2),encoding='utf8')
