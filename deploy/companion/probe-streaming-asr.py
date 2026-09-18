"""Public/consented WAV probe; never opens a microphone or contacts the cloud."""
import argparse,json,sys,time,wave,resource
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument("--root",required=True)
parser.add_argument("--input",required=True)
args=parser.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from apps.companion.streaming_asr import StreamingAsr
with wave.open(args.input,"rb") as w:
    assert w.getframerate()==16000 and w.getnchannels()==1 and w.getsampwidth()==2
    assert 0 < w.getnframes() <= 16000*20, "probe needs at most 20s input"
    pcm=w.readframes(w.getnframes())
t=time.monotonic(); asr=StreamingAsr(args.root); init=time.monotonic()-t
rows=[]
try:
    for name, data, realtime in [("public-1",pcm+bytes(64000),True),("silence",bytes(160000),False),("public-reset",pcm+bytes(64000),False)]:
        asr.exchange(3); start=time.monotonic(); changes=[]; previous=""; endpoint=None; max_request=0
        for offset in range(0,len(data),1920):
            if realtime: time.sleep(max(0,start+offset/32000-time.monotonic()))
            tick=time.monotonic(); v=asr.exchange(1,data[offset:offset+1920]); max_request=max(max_request,time.monotonic()-tick)
            if v['text']!=previous:
                previous=v['text']; changes.append(dict(at_s=round(time.monotonic()-start,4),audio_s=v['audio_s'],text=previous))
            if v.get('endpoint'):
                endpoint=v;break
        final=asr.exchange(2)
        status={}
        for line in open('/proc/%s/status'%asr.process.pid):
            if line.startswith(('VmRSS:','VmHWM:','Threads:')): key,val=line.split(':',1); status[key]=val.strip()
        rows.append(dict(name=name,wall_s=time.monotonic()-start,changes=changes,endpoint=endpoint,final=final,max_request_s=max_request,process=status))
finally:
    asr.close()
assert rows[0]["final"]["text"] and rows[0]["final"]["text"] == rows[2]["final"]["text"], "reset changed transcript"
assert not rows[1]["final"]["text"], "silence produced transcript"
assert all(row["endpoint"] for row in rows), "missing endpoint"
print(json.dumps(dict(init_s=init,rows=rows,child_cpu_s=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime+resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime),ensure_ascii=False,indent=2))
