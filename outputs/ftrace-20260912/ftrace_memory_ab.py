from pathlib import Path
import subprocess,time,json
f=Path('/userdata/rtctrl-face-video');d=f/'ftrace-next';out=d/'memory-ab';out.mkdir(exist_ok=True)
subprocess.run(['sh','stop-video.sh'],cwd=f,check=True);p=None;results=[]
try:
    for i,name in enumerate(('neon','release','release','neon')):
        case=out/(str(i)+'-'+name);case.mkdir(exist_ok=True);exe=d/('rtctrl_face_video_'+name);exe.chmod(0o755)
        args=[str(exe),'--device','/dev/video31','--detector','models/detector.rknn','--recognizer','models/recognizer.rknn','--gallery','gallery.json','--threshold','0.5','--input-type','native-fp16','--jpeg-encoder','mpp','--yuv-matrix','bt601','--yuv-range','full','--frame-converter','rga-direct','--capture-width','2112','--capture-height','1568','--jpeg-mode','async']
        with (case/'app.log').open('w') as log:p=subprocess.Popen(args,cwd=f,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        time.sleep(4)
        if p.poll() is not None:raise RuntimeError('app failed')
        with (case/'monitor.log').open('w') as log:subprocess.run(['python3','/tmp/fps30_monitor.py',str(p.pid),'20',str(case)],stdout=log,stderr=log,check=True)
        result=json.loads((case/'summary.json').read_text());result.update(variant=name,case=i);results.append(result);(out/'results.json').write_text(json.dumps(results,indent=2))
        print('CASE',i,name,'fps',result['effective_fps'],'cpu',result['statistics']['cpu_percent_one_core']['mean'],'pss',result['statistics']['pss_kb']['mean'],'faces',result['samples_with_faces'],flush=True)
        p.terminate();p.wait(timeout=10);p=None;time.sleep(1)
finally:
    if p and p.poll() is None:p.terminate();p.wait(timeout=10)
    subprocess.run(['sh','start-optimized-video.sh','0.5'],cwd=f,check=True)
