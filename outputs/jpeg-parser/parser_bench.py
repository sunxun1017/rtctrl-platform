import importlib.util, json, time, random, sys
from pathlib import Path
b=Path(__file__).parent
def module(name):
    spec=importlib.util.spec_from_file_location(name,b/('preview_parser_'+name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m
mods={x:module(x) for x in ('before','after')}
sample=(b/'parser-sample.jpg').read_bytes()
chunks=[sample[n:n+16384] for n in range(0,len(sample),16384)]
# Actual JPEG plus bytewise boundaries around stuffing, restarts and fill bytes.
special=b'\xff\xd8\xff\xe0\x00\x06ab\xff\xd9\xff\xda\x00\x02abc'+b'\xff\x00'*100+b'\xff\xd0xyz\xff\xff\xd9'
for payload in (special,sample):
    for seed in range(20):
        rng=random.Random(seed)
        stream=payload*3
        pieces=[]
        while stream:
            n=rng.randrange(1,1000);pieces.append(stream[:n]);stream=stream[n:]
        for m in mods.values():
            parser=m.JpegFrames();actual=[]
            for piece in pieces: actual.extend(parser.feed(piece))
            assert actual==[payload]*3
for split in range(len(special)+1):
    p=mods['after'].JpegFrames()
    assert list(p.feed(special[:split]))+list(p.feed(special[split:]))==[special]
results=[]
for mode in ('before','after','after','before','before','after'):
    p=mods[mode].JpegFrames();count=0
    begin=time.process_time()
    for n in range(1500):
        for chunk in chunks:
            for frame in p.feed(chunk):
                assert frame==sample
                count+=1
    elapsed=time.process_time()-begin
    row=dict(mode=mode,frames=count,jpeg_bytes=len(sample),cpu_ms_per_frame=elapsed*1000/count)
    results.append(row);print(json.dumps(row),flush=True)
(b/'parser-results.json').write_text(json.dumps(results,indent=2))
