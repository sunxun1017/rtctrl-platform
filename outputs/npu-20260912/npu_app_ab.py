import os,signal,time,subprocess,json
from pathlib import Path
f=Path('/userdata/rtctrl-face-video');d=f/'npu-test';out=d/'app-ab';out.mkdir(exist_ok=True)
old=int((d/'prealloc.pid').read_text())
assert b'rtctrl_face_video_prealloc' in Path('/proc/%d/cmdline'%old).read_bytes()
os.kill(old,signal.SIGTERM);time.sleep(3)
exe=d/'rtctrl_face_video_optimized';exe.chmod(0o755)
common=['--device','/dev/video31','--detector',str(f/'models/detector.rknn'),'--recognizer',str(f/'models/recognizer.rknn'),'--threshold','0.5','--bind','0.0.0.0','--port','8080']
results=[];p=None
def launch(input_type,encoder,log_path):
    with log_path.open('a') as log:
        process=subprocess.Popen([str(exe),*common,'--input-type',input_type,'--jpeg-encoder',encoder],cwd=f,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    (d/'optimized.pid').write_text(str(process.pid));return process
try:
    for index,(input_type,encoder) in enumerate([('float32','opencv'),('uint8','opencv'),('uint8','turbojpeg'),('float32','turbojpeg'),('float32','turbojpeg'),('uint8','turbojpeg'),('uint8','opencv'),('float32','opencv')]):
        label=str(index)+'-'+input_type+'-'+encoder; case=out/label;case.mkdir(exist_ok=True)
        p=launch(input_type,encoder,case/'app.log');time.sleep(4)
        if p.poll() is not None:raise RuntimeError('application startup failed '+label)
        with (case/'monitor.log').open('w') as log:subprocess.run(['python3','/tmp/npu_soak.py',str(p.pid),'20',str(case)],stdout=log,stderr=log,check=True)
        result=json.loads((case/'summary.json').read_text());result.update(label=label,input_type=input_type,encoder=encoder)
        if result['errors'] or result['effective_fps']<1:raise RuntimeError('application sampling failed '+label)
        results.append(result);(out/'results.json').write_text(json.dumps(results,indent=2))
        print('CASE_DONE',label,'fps',result['effective_fps'],'cpu',result['statistics']['cpu_percent_one_core']['mean'],'pss',result['statistics']['pss_kb']['mean'],flush=True)
        p.terminate();p.wait(timeout=10);p=None;time.sleep(1)
finally:
    if p is not None and p.poll() is None:
        p.terminate()
        try:p.wait(timeout=10)
        except subprocess.TimeoutExpired:p.kill();p.wait()
    if len(results)==8:
        p=launch('uint8','turbojpeg',d/'optimized.log')
        print('OPTIMIZED_RUNNING',p.pid,flush=True)
    else:
        with (d/'prealloc.log').open('a') as log:
            p=subprocess.Popen([str(d/'rtctrl_face_video_prealloc'),*common],cwd=f,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        (d/'prealloc.pid').write_text(str(p.pid));print('RESTORED',p.pid,flush=True)
