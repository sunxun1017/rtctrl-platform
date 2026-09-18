#!/usr/bin/env python3
"""Extract Melo CPU prefix and masked RV1126B decoder; validate before optional build."""
import argparse, copy, hashlib, importlib.metadata, json, os
from pathlib import Path
import numpy as np
import onnx
from onnx import helper as h, numpy_helper as nh, TensorProto as TP

LATENT='/Mul_10_output_0'
SPEAKER='/Unsqueeze_6_output_0'
SCALES=(1,8,64,128,256,512)

def extract(source):
    initializers={x.name:x for x in source.graph.initializer}
    embedding=next(x for x in source.graph.initializer if x.name.endswith('emb_g.weight'))
    speaker=nh.to_array(embedding)[1].reshape(1,256,1).copy()
    by_output={out:n for n in source.graph.node for out in n.output}
    chosen=set()
    used=set()
    def visit(name):
        if name in (LATENT,SPEAKER): return
        if name in initializers:
            used.add(name);return
        n=by_output[name]
        if n.name in chosen:return
        chosen.add(n.name)
        for arg in n.input:
            if arg:visit(arg)
    visit('y')
    nodes=[copy.deepcopy(n) for n in source.graph.node if n.name in chosen]
    inits=[copy.deepcopy(initializers[name]) for name in sorted(used)]
    inits.append(nh.from_array(speaker, SPEAKER))
    graph=h.make_graph(nodes,'melo-decoder-sid1',[h.make_tensor_value_info(LATENT,TP.FLOAT,[1,192,'T'])],
                       [h.make_tensor_value_info('y',TP.FLOAT,[1,1,'samples'])],inits)
    model=h.make_model(graph,opset_imports=source.opset_import)
    model.ir_version=source.ir_version
    onnx.checker.check_model(model)
    return model

def mask_model(model,bucket):
    model=copy.deepcopy(model)
    model.graph.input[0].type.tensor_type.shape.dim[2].dim_value=bucket
    model.graph.output[0].type.tensor_type.shape.dim[2].dim_value=bucket*512
    for scale in SCALES:
        model.graph.input.append(h.make_tensor_value_info('mask_'+str(scale),TP.FLOAT,[1,1,bucket*scale]))
    nodes=[];scale=1
    for n in model.graph.node:
        if n.op_type=='ConvTranspose':
            scale*=next(h.get_attribute_value(a)[0] for a in n.attribute if a.name=='strides')
        mask=(n.op_type in ('Conv','ConvTranspose') and n.name!='/dec/cond/Conv') or n.name=='/dec/Add'
        if mask:
            original=n.output[0]; n.output[0]=original+'_unmasked'
            nodes.append(n)
            nodes.append(h.make_node('Mul',[n.output[0],'mask_'+str(scale)],[original],name=n.name+'_mask'))
        else:nodes.append(n)
    del model.graph.node[:];model.graph.node.extend(nodes)
    model=onnx.shape_inference.infer_shapes(model,strict_mode=True)
    onnx.checker.check_model(model)
    return model

def validate(reference,padded,bucket,output_dir):
    import onnxruntime as ort
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    exact=ort.InferenceSession(reference.SerializeToString(),options,providers=['CPUExecutionProvider'])
    masked=ort.InferenceSession(padded.SerializeToString(),options,providers=['CPUExecutionProvider'])
    rng=np.random.default_rng(20260918); report=[]
    for length in (100, min(200, bucket - 42)):
        z=rng.standard_normal((1,192,length)).astype(np.float32)
        baseline=exact.run(None,{LATENT:z})[0]
        inputs={LATENT:np.pad(z,((0,0),(0,0),(0,bucket-length)))}
        for scale in SCALES:
            mask=np.zeros((1,1,bucket*scale),np.float32);mask[:,:,:length*scale]=1
            inputs['mask_'+str(scale)]=mask
        actual=masked.run(None,inputs)[0][:,:,:length*512]
        err=np.abs(actual-baseline)
        record={'length':length,'max_error':float(err.max()),'mean_error':float(err.mean()),'samples':int(actual.size)}
        print(record,flush=True);report.append(record)
        np.savez(output_dir/f'validation-{length}.npz',**inputs,expected=baseline)
        if not np.isfinite(err).all() or err.max()>1e-5:raise ValueError('masked decoder mismatch')
    (output_dir/'mask-validation.json').write_text(json.dumps(report,indent=2))

def extract_prefix(source):
    source=copy.deepcopy(source)
    source.graph.value_info.append(h.make_tensor_value_info(LATENT,TP.FLOAT,[1,192,None]))
    prefix=onnx.utils.Extractor(source).extract_model([v.name for v in source.graph.input],[LATENT])
    prefix.graph.node.append(h.make_node('Reshape',[LATENT,'rtctrl_shape'],['rtctrl_latent']))
    prefix.graph.initializer.append(h.make_tensor('rtctrl_shape',TP.INT64,[3],[1,1,-1]))
    prefix.graph.ClearField('output')
    prefix.graph.output.append(h.make_tensor_value_info('rtctrl_latent',TP.FLOAT,[1,1,None]))
    prefix.metadata_props.extend(source.metadata_props)
    meta=prefix.metadata_props.add();meta.key='rtctrl_output';meta.value='melo_latent_192'
    onnx.checker.check_model(prefix)
    return prefix


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True,help='Original Melo zh_en model.onnx')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--build',action='store_true',help='Build nonquantized RV1126B RKNN using Toolkit2')
    parser.add_argument('--bucket',type=int,default=256)
    args=parser.parse_args()
    if args.bucket not in (192,256):parser.error('supported buckets are 192 and 256')
    output_dir=args.output_dir.resolve();output_dir.mkdir(parents=True,exist_ok=True)
    source_path=args.source.resolve();source=onnx.load(source_path)
    metadata={x.key:x.value for x in source.metadata_props}
    if metadata.get('speaker_id')!='1':raise ValueError('Expected Melo metadata speaker_id=1')
    reference=extract(source);padded=mask_model(reference,args.bucket)
    files={'prefix':'prefix.onnx','decoder_exact':'decoder-exact.onnx',
           'decoder_masked':f'decoder-masked-{args.bucket}.onnx'}
    onnx.save(extract_prefix(source),output_dir/files['prefix'])
    onnx.save(reference,output_dir/files['decoder_exact'])
    onnx.save(padded,output_dir/files['decoder_masked'])
    validate(reference,padded,args.bucket,output_dir)
    toolkit=None
    if args.build:
        from rknn.api import RKNN
        toolkit=importlib.metadata.version('rknn-toolkit2')
        previous=Path.cwd()
        os.chdir(output_dir)  # Toolkit debug files stay with conversion artifacts.
        r=None
        try:
            r=RKNN(verbose=True,verbose_file=str(output_dir/'build-verbose.log'))
            if r.config(target_platform='rv1126b',optimization_level=3)!=0:
                raise RuntimeError('RKNN config failed')
            if r.load_onnx(model=str(output_dir/files['decoder_masked']))!=0:
                raise RuntimeError('RKNN load failed')
            if r.build(do_quantization=False)!=0:raise RuntimeError('RKNN build failed')
            files['rknn']=f'decoder-masked-{args.bucket}.rknn'
            if r.export_rknn(str(output_dir/files['rknn']))!=0:raise RuntimeError('RKNN export failed')
        finally:
            if r is not None:r.release()
            os.chdir(previous)
    manifest={'source':{'file':source_path.name,'sha256':digest(source_path)},
              'config':{'platform':'rv1126b','bucket':args.bucket,'speaker_embedding_row':1,
                        'optimization_level':3,'do_quantization':False,'scales':SCALES,
                        'latent_channels':192,'upsample_factor':512},
              'versions':{'onnx':onnx.__version__,'onnxruntime':importlib.metadata.version('onnxruntime'),
                          'rknn_toolkit2':toolkit},
              'outputs':{key:{'file':name,'sha256':digest(output_dir/name),'bytes':(output_dir/name).stat().st_size}
                         for key,name in files.items()}}
    (output_dir/'conversion-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))

if __name__=='__main__':main()
