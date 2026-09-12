import urllib.request,io,time,json
from PIL import Image
times=[];sizes=set();count=0
with urllib.request.urlopen('http://192.168.50.2:8080/stream.mjpg',timeout=5) as r:
    while count<210:
        line=r.readline()
        if not line:raise RuntimeError('stream ended')
        if not line.startswith(b'--'):continue
        headers={}
        while True:
            line=r.readline()
            if line in (b'\r\n',b'\n'):break
            k,v=line.decode().split(':',1);headers[k.lower()]=v.strip()
        size=int(headers['content-length']);data=r.read(size)
        if len(data)!=size:raise RuntimeError('short JPEG')
        im=Image.open(io.BytesIO(data));im.load();sizes.add(im.size)
        count+=1
        if count>30:times.append(time.monotonic())
result={'decoded_frames':count,'warmup_frames':30,'timed_frames':len(times),'dimensions':sorted(sizes),'interval_s':times[-1]-times[0],'decoded_fps':(len(times)-1)/(times[-1]-times[0]),'saved_images':False,'client':'Windows Python urllib/Pillow, not browser paint FPS'}
open('work/cpu50-final-stream-check.json','w').write(json.dumps(result,indent=2));print(result)
