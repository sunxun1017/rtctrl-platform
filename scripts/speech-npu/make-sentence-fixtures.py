import json,time,wave,hashlib
from pathlib import Path
import numpy as np,onnx,onnxruntime as ort,sherpa_onnx as sh
from onnx import helper,TensorProto
import argparse
p=argparse.ArgumentParser();p.add_argument('model_dir',type=Path);p.add_argument('output_dir',type=Path);args=p.parse_args()
base=args.model_dir;out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
m=onnx.load(base/'model.onnx')
# Instrumentation-only model: same metadata and input contract, returns exact frontend token ids.
c=onnx.ModelProto();c.CopyFrom(m)
c.graph.ClearField('node');c.graph.ClearField('initializer');c.graph.ClearField('output');c.graph.ClearField('value_info')
c.graph.node.extend([helper.make_node('Cast',['tokens'],['tokens_float'],to=TensorProto.FLOAT),helper.make_node('Unsqueeze',['tokens_float','capture_axes'],['audio'])])
c.graph.initializer.extend([helper.make_tensor('capture_axes',TensorProto.INT64,[1],[1])])
c.graph.output.extend([helper.make_tensor_value_info('audio',TensorProto.FLOAT,[1,1,None])])
onnx.checker.check_model(c);onnx.save(c,out/'capture-tokens.onnx')
conf=sh.OfflineTtsConfig(model=sh.OfflineTtsModelConfig(vits=sh.OfflineTtsVitsModelConfig(model=str(out/'capture-tokens.onnx'),lexicon=str(base/'lexicon.txt'),tokens=str(base/'tokens.txt')),num_threads=2),rule_fsts=','.join(str(base/n) for n in ('date.fst','number.fst','phone.fst','new_heteronym.fst')))
capture=sh.OfflineTts(conf)
vconf=conf.model.vits
print('DEFAULTS',vconf,flush=True)
m.graph.output.extend([helper.make_tensor_value_info('/Mul_8_output_0',TensorProto.FLOAT,[1,96,None]),helper.make_tensor_value_info('/Unsqueeze_output_0',TensorProto.FLOAT,[1,256,1])])
opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
session=ort.InferenceSession(m.SerializeToString(),sess_options=opts,providers=['CPUExecutionProvider'])
texts=['你好呀，我是小伴','今天的天气很好，我们一起出去走走吧']
for i,text in enumerate(texts,3):
 d=out/f'sentence-{i}'
 if (d/'meta.json').exists(): raise SystemExit(f'Refusing to overwrite frozen fixture: {d}; choose a new output directory')
 d.mkdir(exist_ok=True)
 chunks=[]
 def callback(samples,progress):
  chunks.append(np.asarray(samples).copy()); return 1
 captured=capture.generate(text,sid=0,speed=1.0,callback=callback)
 assert len(chunks)==1, chunks
 raw=np.asarray(captured.samples)
 assert np.all(raw==np.round(raw)), raw
 tokens=raw.astype(np.int64)
 inputs={'tokens':tokens[None,:],'tokens_lens':np.array([len(tokens)],np.int64),'noise_scale':np.array([vconf.noise_scale],np.float32),'alpha':np.array([1],np.float32),'noise_scale_dur':np.array([vconf.noise_scale_w],np.float32),'speaker':np.array([0],np.int64)}
 begin=time.monotonic();full,latent,speaker=session.run(None,inputs);elapsed=time.monotonic()-begin
 for name,value in [('reference',full),('latent',latent),('speaker',speaker)]: np.save(d/(name+'.npy'),value);value.astype(np.float32).tofile(d/(name+'.f32'))
 pcm=np.clip(full.reshape(-1)*32768,-32768,32767).astype('<i2')
 with wave.open(str(d/'cpu.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(pcm.tobytes())
 report={'text':text,'tokens':tokens.tolist(),'frontend_callback_batches':len(chunks),'frontend':'sherpa-onnx 1.13.8 actual OfflineTts frontend, token-output instrumented same ONNX metadata','rules':['date.fst','number.fst','phone.fst','new_heteronym.fst'],'sid':0,'speed':1.0,'noise_scale':float(vconf.noise_scale),'noise_scale_dur':float(vconf.noise_scale_w),'latent_length':latent.shape[-1],'latent_shape':list(latent.shape),'speaker_shape':list(speaker.shape),'samples':full.size,'sample_rate':8000,'duration':full.size/8000,'cpu_ort_seconds':elapsed,'same_noise_realization':True,'source_sha256':hashlib.sha256((base/'model.onnx').read_bytes()).hexdigest()}
 (d/'meta.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)
