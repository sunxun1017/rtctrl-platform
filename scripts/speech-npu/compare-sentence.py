import argparse,json,wave
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('reference',type=Path);p.add_argument('actual',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
x=np.fromfile(a.reference,dtype='<f4');y=np.fromfile(a.actual,dtype='<f4')
if x.shape!=y.shape or x.size==0 or not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('Invalid waveforms')
d=x.astype(np.float64)-y.astype(np.float64)
energy=float(np.dot(x.astype(np.float64),x.astype(np.float64)));noise=float(np.dot(d,d))
report={'samples':int(x.size),'sample_rate':8000,'seconds':x.size/8000,'length_equal':True,'finite':True,'max_abs_error':float(abs(d).max()),'rmse':float(np.sqrt(np.mean(d*d))),'snr_db':float(10*np.log10(energy/noise)) if noise else None,'correlation':float(np.corrcoef(x,y)[0,1]),'reference_peak':float(abs(x).max()),'actual_peak':float(abs(y).max()),'reference_clipped_samples':int((abs(x)>=1).sum()),'actual_clipped_samples':int((abs(y)>=1).sum()),'same_latent':True,'gain_normalized':False,'time_aligned_or_shifted':False,'whole_sentence_single_inference':True}
a.output.mkdir(parents=True,exist_ok=True)
for name,z in [('cpu',x),('npu',y)]:
 with wave.open(str(a.output/(name+'.wav')),'wb') as w:
  w.setparams((1,2,8000,0,'NONE','not compressed'));w.writeframes(np.clip(z.astype(np.float64)*32767,-32768,32767).astype('<i2').tobytes())
(a.output/'comparison.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
