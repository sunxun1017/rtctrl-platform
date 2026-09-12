import subprocess,json,time,shutil
from pathlib import Path
f=Path('/userdata/rtctrl-face-video');d=f/'cache-swap';out=d/'matched-ab';out.mkdir(exist_ok=True)
backup=d/'rtctrl_face_video_baseline'
if not backup.exists():shutil.copy2(f/'rtctrl_face_video',backup)
subprocess.run(['sh','stop-video.sh'],cwd=f,check=True);p=None;perf=None;results=[]
events='{cycles,instructions,armv8_cortex_a53/l1d_cache/,armv8_cortex_a53/l1d_cache_refill/,armv8_cortex_a53/l2d_cache/,armv8_cortex_a53/l2d_cache_refill/}'
try:
    for i,name in enumerate(('baseline','prefetch')):
        case=out/(str(i)+'-'+name);case.mkdir(exist_ok=True);exe=d/('rtctrl_face_video_'+name);exe.chmod(0o755)
        args=[str(exe),'--device','/dev/video31','--detector','models/detector.rknn','--recognizer','models/recognizer.rknn','--gallery','gallery.json','--threshold','0.5','--input-type','native-fp16','--jpeg-encoder','mpp','--yuv-matrix','bt601','--yuv-range','full','--frame-converter','rga-direct','--capture-width','2112','--capture-height','1568','--jpeg-mode','async']
        with (case/'app.log').open('w') as log:p=subprocess.Popen(args,cwd=f,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        time.sleep(4)
        if p.poll() is not None:raise RuntimeError('app failed')
        with (case/'pmu.txt').open('w') as log:perf=subprocess.Popen(['perf','stat','-x',';','-e',events,'-p',str(p.pid),'--','sleep','20'],stdout=log,stderr=log)
        with (case/'monitor.log').open('w') as log:subprocess.run(['python3','/tmp/fps30_monitor.py',str(p.pid),'20',str(case)],stdout=log,stderr=log,check=True)
        if perf.wait(timeout=5):raise RuntimeError('perf failed')
        perf=None
        result=json.loads((case/'summary.json').read_text());result.update(variant=name,case=i);results.append(result);(out/'results.json').write_text(json.dumps(results,indent=2))
        print('CASE',i,name,'fps',result['effective_fps'],'cpu',result['statistics']['cpu_percent_one_core']['mean'],'faces',result['samples_with_faces'],flush=True)
        p.terminate();p.wait(timeout=10);p=None;time.sleep(1)
finally:
    if perf and perf.poll() is None:perf.terminate();perf.wait(timeout=5)
    if p and p.poll() is None:p.terminate();p.wait(timeout=10)
    subprocess.run(['sh','start-optimized-video.sh','0.5'],cwd=f,check=True)
