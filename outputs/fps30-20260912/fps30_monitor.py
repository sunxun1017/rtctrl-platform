import json, os, re, time, sys, threading, urllib.request, statistics
from pathlib import Path

pid=int(sys.argv[1]); duration=int(sys.argv[2]); out=Path(sys.argv[3]); out.mkdir(parents=True,exist_ok=True)
base=Path('/proc')/str(pid); hz=os.sysconf('SC_CLK_TCK')
start=time.monotonic(); errors=[]; samples=[]; stop=threading.Event(); stream={'bytes':0,'errors':0}
def text(path):
    return Path(path).read_text()
def stream_reader():
    while not stop.is_set():
        try:
            with urllib.request.urlopen('http://127.0.0.1:8080/stream.mjpg',timeout=5) as r:
                while not stop.is_set():
                    b=r.read(16384)
                    if not b: raise RuntimeError('stream EOF')
                    stream['bytes']+=len(b)
        except Exception:
            stream['errors']+=1
            stop.wait(0.5)
threading.Thread(target=stream_reader,daemon=True).start()
previous=None; last_processed=None; last_advance=start
metadata={'pid':pid,'duration_requested_s':duration,'cmdline':text(base/'cmdline').replace('\0',' '),'clock':'monotonic','sample_interval_s':1,'client':'one local continuous MJPEG reader, plus any browser clients','model_gallery_modified':False}
(out/'metadata.json').write_text(json.dumps(metadata,indent=2))
with (out/'samples.jsonl').open('w') as log:
    n=0
    while True:
        now=time.monotonic(); elapsed=now-start
        sample={'elapsed_s':elapsed}
        try:
            fields=text(base/'stat').rsplit(')',1)[1].split(); ticks=int(fields[11])+int(fields[12])
            sample['cpu_percent_one_core']=None if previous is None else 100*(ticks-previous[1])/hz/(now-previous[0]);previous=(now,ticks)
            status=text(base/'status'); smaps=text(base/'smaps_rollup')
            for key in ('VmRSS','VmHWM','VmSize','Threads'):
                m=re.search(r'^'+key+r':\s+(\d+)',status,re.M);sample[key]=int(m[1]) if m else None
            sample['pss_kb']=int(re.search(r'^Pss:\s+(\d+)',smaps,re.M)[1])
            sample['fds']=len(list((base/'fd').iterdir()))
            mem=text('/proc/meminfo')
            for key in ('MemAvailable','CmaFree'):
                m=re.search(r'^'+key+r':\s+(\d+)',mem,re.M);sample[key+'_kb']=int(m[1]) if m else None
            dma=text('/sys/kernel/debug/dma_buf/bufinfo');m=re.search(r'Total\s+(\d+)\s+objects,\s+(\d+)\s+bytes',dma)
            sample['global_dma_objects']=int(m[1]) if m else None;sample['global_dma_bytes']=int(m[2]) if m else None
            sample['npu_load_percent']=int(re.search(r'(\d+)%',text('/sys/kernel/debug/rknpu/load'))[1])
            sample['npu_freq_hz']=int(text('/sys/kernel/debug/rknpu/freq').strip())
            sample['temperature_c']=int(text('/sys/class/thermal/thermal_zone0/temp'))/1000
            with urllib.request.urlopen('http://127.0.0.1:8080/status.json',timeout=2) as r: app=json.load(r)
            for key in ('frame','processed','dropped','fps','detect_ms','recognize_ms','processing_ms','encode_ms','frame_age_ms','captured','latest_overwrites','capture_sequence_gaps','capture_corrupt','capture_fps','capture_convert_ms','capture_acquire_ms','capture_release_ms','consumer_wait_ms','draw_status_ms','ready_age_ms','published','encode_overwrites','publish_fps'):
                sample[key]=app.get(key)
            sample['face_count']=len(app.get('faces',[]))
            if sample['processed']!=last_processed:last_processed=sample['processed'];last_advance=now
            sample['no_advance_s']=now-last_advance
            sample['stream_bytes']=stream['bytes'];sample['stream_errors']=stream['errors']
        except Exception as e:
            sample['error']=str(e);errors.append({'elapsed_s':elapsed,'error':str(e)})
        log.write(json.dumps(sample)+'\n');log.flush();samples.append(sample)
        if n%30==0: print(json.dumps(sample),flush=True)
        if elapsed>=duration:break
        n+=1;time.sleep(max(0,start+n-time.monotonic()))
stop.set()
summary={'elapsed_s':time.monotonic()-start,'sample_count':len(samples),'errors':errors,'stream':stream,'statistics':{}}
for key in samples[-1]:
    vals=[s[key] for s in samples if isinstance(s.get(key),(int,float)) and key!='elapsed_s']
    if not vals:continue
    vals.sort();summary['statistics'][key]={'min':vals[0],'max':vals[-1],'mean':statistics.mean(vals),'p95':vals[min(len(vals)-1,int(.95*len(vals)))]}
valid=[s for s in samples if s.get('pss_kb') is not None]
summary['pss_first_minute_mean_kb']=statistics.mean(s['pss_kb'] for s in valid if s['elapsed_s']<60)
summary['pss_last_minute_mean_kb']=statistics.mean(s['pss_kb'] for s in valid if s['elapsed_s']>duration-60)
summary['samples_with_faces']=sum(s.get('face_count',0)>0 for s in samples)
summary['samples_no_advance_over_3s']=sum(s.get('no_advance_s',0)>3 for s in samples)
if len(valid)>1:
    a,b=valid[0],valid[-1];summary['effective_fps']=(b['processed']-a['processed'])/(b['elapsed_s']-a['elapsed_s'])
if len(valid)>1 and a.get('published') is not None and b.get('published') is not None:summary['effective_publish_fps']=(b['published']-a['published'])/(b['elapsed_s']-a['elapsed_s'])
(out/'summary.json').write_text(json.dumps(summary,indent=2));print('COMPLETE '+json.dumps(summary),flush=True)
