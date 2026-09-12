import io,json,time,urllib.request
from PIL import Image
base='http://192.168.50.2:8080'
times=[];sizes=set();total=0
with urllib.request.urlopen(base+'/stream.mjpg',timeout=5) as response:
    for i in range(180):
        line=response.readline()
        while line in (b'\r\n',b'\n'):line=response.readline()
        assert line.strip()==b'--frame',line
        headers={}
        while True:
            line=response.readline()
            if line in (b'\r\n',b'\n'):break
            key,value=line.decode().split(':',1);headers[key.lower()]=value.strip()
        size=int(headers['content-length']);data=response.read(size)
        assert len(data)==size and data[:2]==b'\xff\xd8' and data[-2:]==b'\xff\xd9'
        with Image.open(io.BytesIO(data)) as image:image.load();sizes.add(image.size)
        total+=size;times.append(time.monotonic())
with urllib.request.urlopen(base+'/status.json',timeout=4) as response:status=json.load(response)
result={'decoded_jpegs':len(times),'network_received_fps':(len(times)-1)/(times[-1]-times[0]),'dimensions':[list(x) for x in sizes],'bytes':total,'status':{k:status.get(k) for k in ('fps','publish_fps','capture_fps','processed','published','latest_overwrites','capture_sequence_gaps','encode_overwrites','input_type','frame_converter','jpeg_mode')}}
with open('work/network-preview.json','w') as f:json.dump(result,f,indent=2)
print(json.dumps(result,indent=2))
