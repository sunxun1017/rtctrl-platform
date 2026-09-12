import os,time,subprocess,json
from pathlib import Path
f=Path('/userdata/rtctrl-face-video');d=f/'fps30-test';out=d/'rga-ab';out.mkdir(exist_ok=True)
exe=d/'rtctrl_face_video_rga';exe.chmod(0o755)
subprocess.run(['sh','stop-video.sh'],cwd=f,check=True)
p=None;results=[]
try:
    for i,converter in enumerate(('cpu','rga','rga','cpu')):
        case=out/(str(i)+'-'+converter);case.mkdir(exist_ok=True)
        args=[str(exe),'--device','/dev/video31','--detector','models/detector.rknn','--recognizer','models/recognizer.rknn','--gallery','gallery.json','--threshold','0.5','--input-type','uint8','--jpeg-encoder','turbojpeg','--yuv-matrix','bt601','--yuv-range','full','--frame-converter',converter]
        with (case/'app.log').open('w') as log:p=subprocess.Popen(args,cwd=f,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        time.sleep(4)
        if p.poll() is not None:raise RuntimeError('app failed '+str(case))
        with (case/'monitor.log').open('w') as log:subprocess.run(['python3','/tmp/fps30_monitor.py',str(p.pid),'20',str(case)],stdout=log,stderr=log,check=True)
        result=json.loads((case/'summary.json').read_text());result['converter']=converter;result['case']=i
        results.append(result);(out/'results.json').write_text(json.dumps(results,indent=2))
        print('CASE',i,converter,result['effective_fps'],result['statistics']['cpu_percent_one_core']['mean'],flush=True)
        p.terminate();p.wait(timeout=10);p=None;time.sleep(1)
finally:
    if p and p.poll() is None:p.terminate();p.wait(timeout=10)
    subprocess.run(['sh','start-video.sh','0.5'],cwd=f,env=dict(os.environ,RKNN_INPUT_TYPE='uint8',PREVIEW_JPEG_ENCODER='turbojpeg'),check=True)
