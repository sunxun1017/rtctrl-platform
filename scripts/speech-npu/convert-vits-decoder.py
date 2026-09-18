import os,json,hashlib,time
from pathlib import Path
import onnx,numpy as np
from onnx import helper,TensorProto
from rknn.api import RKNN
import argparse
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path);args=p.parse_args()
out=args.output;out.mkdir(parents=True,exist_ok=True)
m=onnx.load(args.source)
nodes=[n for n in m.graph.node if n.name.startswith('/decoder/')]
used={x for n in nodes for x in n.input};initial=[i for i in m.graph.initializer if i.name in used]
length=int(os.environ.get('LATENT_LENGTH','16'))
inputs=[helper.make_tensor_value_info('/Mul_8_output_0',TensorProto.FLOAT,[1,96,length]),helper.make_tensor_value_info('/Unsqueeze_output_0',TensorProto.FLOAT,[1,256,1])]
outputs=[helper.make_tensor_value_info('/decoder/output_conv/output_conv.2/Tanh_output_0',TensorProto.FLOAT,[1,1,length*256])]
graph=helper.make_graph(nodes,'aishell3_vits_decoder',inputs,outputs,initial)
model=helper.make_model(graph,opset_imports=list(m.opset_import));model.ir_version=m.ir_version
onnx.checker.check_model(model);path=out/f'decoder-l{length}.onnx';onnx.save(model,path)
info={'latent_length':length,'input_shapes':[[1,96,length],[1,256,1]],'output_shape':[1,1,length*256],'source_sha256':hashlib.sha256((args.source).read_bytes()).hexdigest(),'onnx_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'nodes':len(nodes),'target':'rv1126b','quantized':False}
(out/f'decoder-l{length}.json').write_text(json.dumps(info,indent=2));print('EXTRACTED',info,flush=True)
r=RKNN(verbose=False)
try:
 print('CONFIG',r.config(target_platform='rv1126b'),flush=True)
 ret=r.load_onnx(model=str(path)); print('LOAD',ret,flush=True)
 if ret:raise SystemExit(ret)
 start=time.monotonic();ret=r.build(do_quantization=False);print('BUILD',ret,'SECONDS',time.monotonic()-start,flush=True)
 if ret:raise SystemExit(ret)
 ret=r.export_rknn(str(out/f'decoder-l{length}.rknn'));print('EXPORT',ret,flush=True)
 if ret:raise SystemExit(ret)
 info['rknn_sha256']=hashlib.sha256((out/f'decoder-l{length}.rknn').read_bytes()).hexdigest()
 (out/f'decoder-l{length}.json').write_text(json.dumps(info,indent=2))
finally:r.release()
