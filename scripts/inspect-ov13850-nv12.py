#!/usr/bin/env python3
"""Inspect tightly packed NV12 using explicit BT.601 full-range conversion.
Requires numpy and Pillow. ROI is x,y,width,height in full-resolution pixels.
This reports rendered RGB ratios, not RAW WB calibration gains.
"""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('input',type=Path);p.add_argument('--output',required=True,type=Path)
p.add_argument('--width',type=int,default=2112);p.add_argument('--height',type=int,default=1568)
p.add_argument('--roi',type=int,nargs=4,default=[750,600,600,400]);a=p.parse_args()
w,h=a.width,a.height
if w<=0 or h<=0 or w%2 or h%2: p.error('even positive dimensions required')
b=np.fromfile(a.input,dtype=np.uint8)
if b.size!=w*h*3//2:p.error('expected exactly one tightly packed frame; check stride and plane offsets')
y=b[:w*h].reshape(h,w).astype(np.float32)
uv=b[w*h:].reshape(h//2,w//2,2).repeat(2,0).repeat(2,1).astype(np.float32)-128
u,v=uv[:,:,0],uv[:,:,1]
rgb=np.stack([y+1.402*v,y-.344136*u-.714136*v,y+1.772*u],axis=2).clip(0,255)
x0,y0,rw,rh=a.roi
if min(x0,y0)<0 or min(rw,rh)<=0 or x0+rw>w or y0+rh>h:p.error('ROI outside image')
roi=rgb[y0:y0+rh,x0:x0+rw];m=roi.mean(axis=(0,1))
report={'decode':'NV12 / BT.601 / full range','roi':a.roi,'rgb_mean':m.tolist(),'r_over_g':float(m[0]/max(m[1],1e-6)),'b_over_g':float(m[2]/max(m[1],1e-6)),'clipped_fraction':float(np.mean((roi<=0)|(roi>=255))),'not_raw_calibration':True}
a.output.parent.mkdir(parents=True,exist_ok=True)
Image.fromarray(rgb.astype(np.uint8)).resize((w//2,h//2)).save(a.output)
a.output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report,indent=2))
