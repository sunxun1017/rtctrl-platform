#!/usr/bin/env python3
"""Strict finite hex UART export; preserves failures, never infers missing bytes."""
import argparse, hashlib, json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PRIVATE=ROOT/'outputs/rk3568-pid1-20261005/private'
def save(path,data):
    with path.open('xb') as f: f.write(data)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','extract'])
    p.add_argument('--label',required=True)
    p.add_argument('--file',action='append',required=True,help='key=board-path:bytes:sha256')
    p.add_argument('--raw-name',action='append',required=True)
    p.add_argument('--block-size',type=int,default=1024)
    p.add_argument('--offset',type=int,action='append')
    a=p.parse_args()
    assert re.fullmatch('[a-z0-9-]{1,90}',a.label)
    assert a.block_size in [256,1024]
    assert all(re.fullmatch('[a-z0-9.-]{1,120}',n) for n in a.raw_name)
    pairs=[]
    for item in a.file:
        key,desc=item.split('=',1); board,n,h=desc.rsplit(':',2); n=int(n)
        assert re.fullmatch('[a-z0-9.-]{1,110}',key)
        assert re.fullmatch('/[a-zA-Z0-9/._-]{1,180}',board) and '..' not in board.split('/')
        assert board in ['/sys/firmware/fdt','/sys/kernel/notes'] or board.startswith('/tmp/audio/')
        assert 0<=n<=524288 and re.fullmatch('[0-9a-f]{64}',h)
        pairs.append((key,board,n,h))
    assert len(set(k for k,b,n,h in pairs))==len(pairs) and len(pairs)<=60
    out=HERE/'build/board-exports-v5'; out.mkdir(exist_ok=True)
    if a.action=='prepare':
        steps=[]
        for key,board,n,h in pairs:
            steps += [{'command':"printf 'AUDIO_BOARD_FILE bytes=%s path="+board+"\\n' \"$(stat -c %s "+board+")\" && sha256sum "+board,'wait':1,'expect':h+'  '+board}]
            offsets=a.offset if a.offset is not None else range(0,n,a.block_size)
            for offset in offsets:
                assert 0<=offset<n and offset%a.block_size==0
                size=min(a.block_size,n-offset)
                begin=f'AUDIO_EXPORT_CHUNK path={board} offset={offset} bytes={size} encoding=hex'
                end=f'AUDIO_EXPORT_CHUNK_END path={board} offset={offset}'
                steps.append({'command':f"echo {begin} && dd if={board} bs={a.block_size} skip={offset//a.block_size} count=1 2>/dev/null | hexdump -v -e '16/1 \"%02x\" \"\\n\"'; echo {end}", 'wait':0.2})
            steps.append({'command':'sha256sum '+board,'wait':1,'expect':h+'  '+board})
        save(out/(a.label+'.json'),(json.dumps(steps,indent=2)+'\n').encode())
        print(json.dumps({'prepared':a.label,'files':len(pairs),'steps':len(steps),'device_execution':False})); return
    raws=[(PRIVATE/n).read_bytes() for n in a.raw_name]
    texts=[r.decode('ascii').replace('\r','') for r in raws]
    records={}; payloads={}; errors=[]
    for key,board,n,h in pairs:
        assert any(re.search(r'^AUDIO_BOARD_FILE bytes='+str(n)+' path='+re.escape(board)+r'$',t,re.M) for t in texts)
        assert all(re.search('^'+h+'  '+re.escape(board)+r'$',t,re.M) for t in texts)
        blocks=[]
        for t in texts:
            rx=r'^AUDIO_EXPORT_CHUNK path='+re.escape(board)+r' offset=(\d+) bytes=(\d+) encoding=hex\n([0-9a-f \n]*)\nAUDIO_EXPORT_CHUNK_END path='+re.escape(board)+r' offset=\1$'
            for off,size,encoded in re.findall(rx,t,re.M):
                encoded=encoded.replace('\n','').replace(' ','')
                if len(encoded)==int(size)*2: blocks.append((int(off),bytes.fromhex(encoded)))
        combined=bytearray(n); present=bytearray(n)
        for off,data in blocks:
            assert off+len(data)<=n
            for i,v in enumerate(data,off):
                assert not present[i] or combined[i]==v,('conflicting export',key,i)
                combined[i]=v;present[i]=1
        missing=[i for i,v in enumerate(present) if not v]
        if missing:
            errors.append({'file':key,'missing_bytes':len(missing),'missing_1024_offsets':sorted(set(i//1024*1024 for i in missing))}); continue
        data=bytes(combined); assert hashlib.sha256(data).hexdigest()==h,(key,'full SHA mismatch')
        host=out/key; assert not host.exists(); payloads[host]=data
        records[key]={'board_path':board,'host_path':host.relative_to(ROOT).as_posix(),'bytes':n,'sha256':h,'metadata_raw_path':(PRIVATE/a.raw_name[0]).relative_to(ROOT).as_posix(),'transfer_raw_paths':[(PRIVATE/name).relative_to(ROOT).as_posix() for name in a.raw_name]}
    if errors:
        print(json.dumps({'incomplete':errors})); raise SystemExit(2)
    receipt=out/(a.label+'-extraction.json'); assert not receipt.exists()
    for path,data in payloads.items(): save(path,data)
    record={'files':records,'raws':{name:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in zip(a.raw_name,raws)},'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'no_missing_bytes_inferred_or_padded':True}
    save(receipt,(json.dumps(record,indent=2)+'\n').encode())
    print(json.dumps({'exported':a.label,'files':len(records),'bytes':sum(x['bytes'] for x in records.values())}))
if __name__=='__main__': main()
