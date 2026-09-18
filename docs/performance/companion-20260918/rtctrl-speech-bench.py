import json,socket,tempfile,shutil,time,statistics,urllib.request,os
from pathlib import Path
pid=int(os.environ.get('WORKER_PID','31061'))
def snap():
 d={}
 for line in Path('/proc/%d/status'%pid).read_text().splitlines():
  if line.startswith(('VmRSS:','VmHWM:','Threads:')):d[line.split(':')[0]]=int(line.split()[1])
 s=Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split();d['cpu_ticks']=int(s[11])+int(s[12])
 try:
  status=json.load(urllib.request.urlopen('http://127.0.0.1:8092/api/status',timeout=2));d['face_fps']=status.get('face',{}).get('fps')
 except Exception:pass
 return d
with tempfile.TemporaryDirectory(prefix='rtctrl-voice-') as directory:
 source=directory+'/input.wav';shutil.copy('/userdata/rtctrl-speech/sherpa-onnx-zipformer-ctc-small-zh-int8-2025-07-16/test_wavs/0.wav',source)
 for index in range(4):
  for operation in ('asr','tts'):
   req={'operation':operation,'input':source,'output':directory+'/out.'+('json' if operation=='asr' else 'wav'),'text':'你好呀，我是小伴。今天有什么想和我聊的吗？'}
   before=snap();start=time.monotonic()
   with socket.socket(socket.AF_UNIX) as peer:
    peer.settimeout(60);peer.connect('/run/rtctrl-companion/speech.sock');peer.sendall(json.dumps(req).encode()+b'\n');result=json.loads(peer.recv(4096))
   elapsed=time.monotonic()-start;after=snap()
   print(json.dumps({'round':index,'op':operation,'seconds':round(elapsed,4),'ok':result.get('ok'),'cpu_seconds':(after['cpu_ticks']-before['cpu_ticks'])/os.sysconf('SC_CLK_TCK'),'after':after}),flush=True)
