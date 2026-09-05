from pathlib import Path
import subprocess,json,tempfile,hashlib
import argparse
ap=argparse.ArgumentParser(description='Experiment invariants, not a complete ISP35 schema validator')
ap.add_argument('--sdk-root',required=True,type=Path)
args=ap.parse_args()
r=Path(__file__).resolve().parents[1]; sdk=args.sdk_root
(r/'work').mkdir(exist_ok=True)
g=r/'scripts/generate-ov13850-isp35.py'
with tempfile.TemporaryDirectory(prefix='iq-check-',dir=r/'work') as t:
 for wb in ['unity','borrowed-auto']:
  out=Path(t)/wb
  subprocess.run(['python3',str(g),'--sdk-root',str(sdk),'--out-dir',str(out),'--wb',wb],check=True)
  d=json.loads((out/'ov13850_ATK-MCOV13850_default.json').read_text());s=d['sensor_calib'];c=d['main_scene'][0]['sub_scene'][0]['scene_isp35']
  assert s['resolution']==dict(width=2112,height=1568)
  assert s['CISTimeSet']['Linear']['CISLinTimeRegMaxFac']['fCoeff']==[1,16]
  assert s['CISTimeSet']['Linear']['CISTimeRegMin']==2
  assert s['CISTimeSet']['Linear']['CISTimeLinePerReg']==1
  assert s['CISHdrSet']['hdr_en']==0 and s['CISFlip']==0
  assert all(s['CISGainSet'][k]==dict(Min=1,Max=1) for k in ['CISDgainRange','CISIspDgainRange'])
  assert c['lsc']['tunning']['en']==c['ccm']['tunning']['en']==c['blc']['en']==0
  assert all(c[k]['en']==0 for k in ['ynr','cnr','sharp','enh','bayertnr'])
  assert c['ae_calib']['commCtrl']['frmRate']['sw_aeT_frmRate_mode']=='ae_frmRate_fix_mode'
  assert c['csm']['stMan']['sta']['hw_csmT_full_range']==1
  for gain,expected in [(1,16),(2,32),(4,64),(8,128),(15.5,248)]:
   lo,hi,c1,c0,m0,rmin,rmax=s['Gain2Reg']['GainRange'];reg=max(rmin,min(rmax,int(c1*gain**m0-c0+.5)));assert reg==expected
  assert round(0.03*(4800*1664*30)/4800)==1498
  assert set(json.loads((out/'provenance.json').read_text())['modules'])==set(c)
  print(wb,'parameter invariants PASS; NOT full schema validation')
print('PASS')
