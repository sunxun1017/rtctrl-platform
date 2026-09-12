import subprocess,json,time,urllib.request
from pathlib import Path
f=Path('/userdata/rtctrl-face-video');o=f/'cache-swap';o.mkdir(exist_ok=True);pid=(f/'video.pid').read_text().strip()
def snapshot():
    s=json.load(urllib.request.urlopen('http://127.0.0.1:8080/status.json',timeout=3))
    return {'monotonic':time.monotonic(),'swaps':Path('/proc/swaps').read_text(),'vmstat':Path('/proc/vmstat').read_text(),'meminfo':Path('/proc/meminfo').read_text(),'process_stat':Path('/proc',pid,'stat').read_text(),'smaps_rollup':Path('/proc',pid,'smaps_rollup').read_text(),'status':{k:s.get(k) for k in ['processed','published','latest_overwrites','encode_overwrites','capture_sequence_gaps']},'face_count':len(s.get('faces',[]))}
before=snapshot();samples=[]
events='{cycles,instructions,armv8_cortex_a53/l1d_cache/,armv8_cortex_a53/l1d_cache_refill/,armv8_cortex_a53/l2d_cache/,armv8_cortex_a53/l2d_cache_refill/},task-clock,major-faults,minor-faults'
with (o/'perf-stat.txt').open('w') as log:
    p=subprocess.Popen(['perf','stat','-x',';','-e',events,'-p',pid,'--','sleep','20'],stdout=log,stderr=log)
    while p.poll() is None:
        s=json.load(urllib.request.urlopen('http://127.0.0.1:8080/status.json',timeout=3));samples.append({'time':time.monotonic(),'face_count':len(s.get('faces',[])),'processed':s['processed']});time.sleep(1)
    rc=p.wait()
after=snapshot();(o/'snapshot.json').write_text(json.dumps({'pid':pid,'perf_exit':rc,'before':before,'after':after,'samples':samples},indent=2));print('DONE',rc,flush=True)
