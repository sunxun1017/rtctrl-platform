"""Compare complete WAV vs streamed PCM; fixed text, no mic/playback/cloud."""
import argparse,json,sys,time,tempfile,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--config",required=True)
parser.add_argument("--rounds",type=int,choices=range(1,6),default=3)
args=parser.parse_args()
from apps.companion.local_voice import LocalVoiceTransport
from apps.companion.audio import PcmStreamChunk
c=json.load(open(args.config))
texts=[('short','你好，现在可以连续对话了。'),('dialogue','你今天过得怎么样？如果有点累，我们就先休息一会儿。等你准备好了，再慢慢跟我说，我会认真听的。')]
for index in range(args.rounds):
 for name,text in texts:
  for mode in ('whole','stream'):
   blocks=[];metrics={};start=time.monotonic()
   def event(v):
    if isinstance(v,PcmStreamChunk) and v.data:blocks.append(dict(at_s=time.monotonic()-start,audio_s=len(v.data)/(v.sample_rate*2)))
    elif isinstance(v,dict) and v.get('type')=='latency':metrics.update(v['values'])
   t=LocalVoiceTransport(c,event,lambda e:None);t._closed=False
   try:
    if mode=='whole':
     with tempfile.TemporaryDirectory(prefix='rtctrl-voice-') as directory:
      out=directory+'/reply.wav';t._execute(0,c['local_tts_command'],'local_tts_timeout_s',input=directory+'/unused',output=out,text=text)
      with wave.open(out,'rb') as w:blocks.append(dict(at_s=time.monotonic()-start,audio_s=w.getnframes()/w.getframerate()))
    else:t._stream_tts(0,text)
   finally:
    t.close()
   total=time.monotonic()-start
   print(json.dumps(dict(round=index,name=name,mode=mode,total_s=total,blocks=blocks,timing=metrics)),flush=True)
