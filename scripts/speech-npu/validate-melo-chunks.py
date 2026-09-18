#!/usr/bin/env python3
"""Prove conservative graph halo, then compare stitched FP32 decoder outputs."""
from pathlib import Path
import argparse, json
import numpy as np
import onnx
import onnxruntime as ort
LATENT='/Mul_10_output_0'
SCALES=(1,8,64,128,256,512)

def receptive_interval(model,start,end):
    needed={'y':(start,end)}
    initializers={x.name for x in model.graph.initializer}
    def merge(name,lo,hi):
        if name in initializers:return
        prev=needed.get(name)
        needed[name]=(min(lo,prev[0]),max(hi,prev[1])) if prev else (lo,hi)
    for node in reversed(model.graph.node):
        if node.output[0] not in needed:continue
        lo,hi=needed[node.output[0]]
        attr={a.name:onnx.helper.get_attribute_value(a) for a in node.attribute}
        if node.op_type in ('Conv','ConvTranspose'):
            k=attr['kernel_shape'][0];s=attr.get('strides',[1])[0]
            d=attr.get('dilations',[1])[0];p=attr.get('pads',[0,0])[0]
            if node.op_type=='Conv':lo,hi=lo*s-p,hi*s-p+(k-1)*d
            else:lo,hi=-(-(lo+p-(k-1)*d)//s),(hi+p)//s
            merge(node.input[0],lo,hi)
        elif node.op_type in ('Add','Div','Mul','LeakyRelu','Tanh','Identity'):
            for arg in node.input:merge(arg,lo,hi)
        elif node.op_type!='Constant':raise ValueError('Unhandled op '+node.op_type)
    return needed[LATENT]

def decode_chunked(session,latent,halo=16,bucket=256):
    if latent.ndim!=3 or latent.shape[:2]!=(1,192) or latent.shape[-1]<1 or not np.isfinite(latent).all():
        raise ValueError('Expected finite latent [1,192,L], L>0')
    length=latent.shape[-1];core=bucket-2*halo
    if core<=0:raise ValueError('invalid halo')
    parts=[]
    for start in range(0,length,core):
        end=min(length,start+core)
        source_start=max(0,start-halo);source_end=min(length,end+halo)
        count=source_end-source_start
        inputs={LATENT:np.pad(latent[:,:,source_start:source_end],((0,0),(0,0),(0,bucket-count)))}
        for scale in SCALES:
            mask=np.zeros((1,1,bucket*scale),np.float32);mask[:,:,:count*scale]=1
            inputs['mask_'+str(scale)]=mask
        output=session.run(None,inputs)[0]
        parts.append(output[:,:,(start-source_start)*512:(end-source_start)*512])
    result=np.concatenate(parts,axis=-1)
    if result.shape!=(1,1,length*512):raise ValueError('Unexpected chunk output shape')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',type=Path,required=True,help='Output directory from convert-melo.py')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--latents-dir',type=Path,help='Optional real [1,192,L] float32 .npy inputs')
    parser.add_argument('--lengths',type=int,nargs='+',default=[257,600,1000])
    parser.add_argument('--bucket',type=int,default=256)
    parser.add_argument('--halo',type=int,default=16)
    args=parser.parse_args()
    if min(args.lengths)<1 or args.halo<0 or args.bucket<=2*args.halo:parser.error('Invalid lengths/bucket/halo')
    root=args.model_dir.resolve();output_dir=args.output_dir.resolve();output_dir.mkdir(parents=True,exist_ok=True)
    model=onnx.load(root/'decoder-exact.onnx')
    # Middle-frame interval avoids confusing model global boundaries with halo.
    interval=receptive_interval(model,1000*512,1001*512-1)
    halo=max(1000-interval[0],interval[1]-1000)
    print('dependency interval',interval,'required halo',halo,flush=True)
    if args.halo<halo:raise ValueError('Requested halo is below graph dependency bound')
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    exact=ort.InferenceSession(str(root/'decoder-exact.onnx'),options,providers=['CPUExecutionProvider'])
    masked=ort.InferenceSession(str(root/f'decoder-masked-{args.bucket}.onnx'),options,providers=['CPUExecutionProvider'])
    rng=np.random.default_rng(98765);records=[]
    for length in args.lengths:
        latent=rng.standard_normal((1,192,length)).astype(np.float32)
        baseline=exact.run(None,{LATENT:latent})[0]
        for h in sorted({halo,args.halo}):
            actual=decode_chunked(masked,latent,h,args.bucket)
            error=np.abs(actual-baseline)
            record={'length':length,'halo':h,'core_frames':args.bucket-2*h,'max_error':float(error.max()),'mean_error':float(error.mean()),'output_samples':actual.size}
            print(record,flush=True);records.append(record)
            if not np.isfinite(error).all() or error.max()>1e-5:raise ValueError('Chunk equivalence threshold exceeded')
    real_files=sorted(args.latents_dir.glob('*.npy')) if args.latents_dir else []
    real_latents=[(p.name,np.load(p)) for p in real_files]
    if real_latents:
        real_latents.append(('concatenated-real-latents',np.concatenate([x for _,x in real_latents],axis=-1)))
    for name,latent in real_latents:
        baseline=exact.run(None,{LATENT:latent})[0]
        actual=decode_chunked(masked,latent,args.halo,args.bucket)
        error=np.abs(actual-baseline)
        record={'name':name,'length':latent.shape[-1],'halo':args.halo,'max_error':float(error.max()),'mean_error':float(error.mean()),'output_samples':actual.size}
        print(record,flush=True);records.append(record)
        if not np.isfinite(error).all() or error.max()>1e-5:raise ValueError('Chunk equivalence threshold exceeded')
    (output_dir/'chunk-validation.json').write_text(json.dumps({'dependency_interval_for_frame_1000':interval,'required_halo':halo,'recommended_halo':args.halo,'bucket':args.bucket,'records':records},indent=2))
if __name__=='__main__':main()
