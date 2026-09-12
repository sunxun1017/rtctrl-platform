import os,time,subprocess,json,shutil,urllib.request,hashlib
from pathlib import Path
f=Path('/userdata/rtctrl-face-video');d=f/'cpu50-test'
results=json.loads((d/'ab/results.json').read_text());assert len(results)==8 and all(not x['errors'] for x in results)
for name in ('rtctrl_face_video','start-video.sh','start-optimized-video.sh'):
    backup=d/(name+'.before-deploy')
    if not backup.exists():shutil.copy2(f/name,backup)
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [f/'gallery.json',f/'models/detector.rknn',f/'models/recognizer.rknn']}
(d/'protected-hashes-before.json').write_text(json.dumps(before,indent=2))
subprocess.run(['sh','stop-video.sh'],cwd=f,check=True)
try:
    for name,source in [('rtctrl_face_video','rtctrl_face_video_candidate'),('start-video.sh','start-video.next.sh'),('start-optimized-video.sh','start-optimized-video.next.sh')]:
        tmp=f/(name+'.next');shutil.copy2(d/source,tmp);tmp.chmod(0o755);os.replace(tmp,f/name)
    subprocess.run(['sh','start-optimized-video.sh','0.5'],cwd=f,check=True)
    time.sleep(3)
    status=json.load(urllib.request.urlopen('http://127.0.0.1:8080/status.json',timeout=4));assert status['published']>5
except Exception:
    subprocess.run(['sh','stop-video.sh'],cwd=f)
    for name in ('rtctrl_face_video','start-video.sh','start-optimized-video.sh'):shutil.copy2(d/(name+'.before-deploy'),f/name)
    subprocess.run(['sh','start-optimized-video.sh','0.5'],cwd=f,check=True);raise
pid=(f/'video.pid').read_text().strip();print('DEPLOYED',pid,flush=True)
with (d/'final-monitor.log').open('w') as log:subprocess.run(['python3','/tmp/fps30_monitor.py',pid,'60',str(d/'final-monitor')],stdout=log,stderr=log,check=True)
print('MONITOR_DONE',flush=True)
with (d/'final-record.txt').open('w') as log:subprocess.run(['perf','record','-e','cpu-clock','-F','99','-g','-p',pid,'-o',str(d/'final.data'),'--','sleep','20'],stdout=log,stderr=log,check=True)
for label,args in [('self',['--no-children','--percent-limit','0.5']),('dso',['--no-children','--sort','dso','--percent-limit','0'])]:
    with (d/('final-'+label+'.txt')).open('w') as log:subprocess.run(['perf','report','--stdio','-i',str(d/'final.data'),*args],stdout=log,stderr=log,check=True)
after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [f/'gallery.json',f/'models/detector.rknn',f/'models/recognizer.rknn']}
assert before==after
(d/'protected-hashes-after.json').write_text(json.dumps(after,indent=2))
print('DONE',flush=True)
