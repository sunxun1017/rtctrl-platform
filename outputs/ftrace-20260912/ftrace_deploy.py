import os,subprocess,time,json,shutil,hashlib,urllib.request
from pathlib import Path
f=Path('/userdata/rtctrl-face-video');d=f/'ftrace-next'
assert len(json.loads((d/'memory-ab/results.json').read_text()))==4
protected=[f/'gallery.json',f/'models/detector.rknn',f/'models/recognizer.rknn']
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
shutil.copy2(d/'rtctrl_face_video_release',f/'rtctrl_face_video.next');(f/'rtctrl_face_video.next').chmod(0o755)
subprocess.run(['sh','stop-video.sh'],cwd=f,check=True)
try:
    os.replace(f/'rtctrl_face_video.next',f/'rtctrl_face_video');subprocess.run(['sh','start-optimized-video.sh','0.5'],cwd=f,check=True);time.sleep(3)
    s=json.load(urllib.request.urlopen('http://127.0.0.1:8080/status.json',timeout=4));assert s['published']>5
except Exception:
    subprocess.run(['sh','stop-video.sh'],cwd=f);shutil.copy2(d/'rtctrl_face_video_baseline',f/'rtctrl_face_video');subprocess.run(['sh','start-optimized-video.sh','0.5'],cwd=f,check=True);raise
pid=(f/'video.pid').read_text().strip();print('DEPLOYED',pid,flush=True)
with (d/'monitor.log').open('w') as log:subprocess.run(['python3','/tmp/fps30_monitor.py',pid,'60',str(d/'final-monitor')],stdout=log,stderr=log,check=True)
print('MONITOR_DONE',flush=True)
with (d/'final-trace.log').open('w') as log:subprocess.run(['python3','/tmp/ftrace_npu_capture.py','final'],stdout=log,stderr=log,check=True)
assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
(d/'deployed-manifest.json').write_text(json.dumps({'binary_sha256':hashlib.sha256((f/'rtctrl_face_video').read_bytes()).hexdigest(),'protected_hashes_unchanged':hashes,'pid':pid,'long_soak':False},indent=2));print('DONE',flush=True)
