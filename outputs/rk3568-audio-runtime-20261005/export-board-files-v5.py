#!/usr/bin/env python3
"""Finite original-file export commands and fail-closed UART extraction for v5."""
import argparse, base64, hashlib, json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PRIVATE = ROOT / 'outputs/rk3568-pid1-20261005/private'
def save(path, data):
    with path.open('xb') as stream:
        stream.write(data)
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare','extract'])
    p.add_argument('--label', required=True)
    p.add_argument('--file', action='append', required=True, help='key=/absolute/board/path')
    p.add_argument('--raw-name', required=True)
    a=p.parse_args()
    assert re.fullmatch('[a-z0-9-]{1,90}', a.label)
    assert re.fullmatch('[a-z0-9.-]{1,120}', a.raw_name)
    pairs=[]
    for item in a.file:
        key, board=item.split('=',1)
        assert re.fullmatch('[a-z0-9.-]{1,110}',key)
        assert re.fullmatch('/[a-zA-Z0-9/._-]{1,180}',board) and '..' not in board.split('/')
        assert board in ['/sys/firmware/fdt','/sys/kernel/notes'] or board.startswith('/tmp/audio/')
        pairs.append((key,board))
    assert len(set(k for k,b in pairs))==len(pairs) and len(pairs)<=60
    out=HERE/'build/board-exports-v5'
    out.mkdir(exist_ok=True)
    if a.action=='prepare':
        steps=[{'command':'command -v base64','wait':1,'expect':'/bin/base64'}]
        for key, board in pairs:
            steps += [
              {'command':"printf 'AUDIO_BOARD_FILE bytes=%s path="+board+"\\n' \"$(stat -c %s "+board+")\" && sha256sum "+board,'wait':1},
              {'command':'echo AUDIO_EXPORT_BEGIN path='+board+' encoding=base64 && base64 '+board+' && echo AUDIO_EXPORT_END path='+board,'wait':3}]
        save(out/(a.label+'.json'),(json.dumps(steps,indent=2)+'\n').encode())
        print(json.dumps({'prepared':a.label,'files':len(pairs),'device_execution':False}))
        return
    raw_path=PRIVATE/a.raw_name
    raw=raw_path.read_bytes()
    text=raw.decode('ascii').replace('\r','')
    records={}
    payloads={}
    for key,board in pairs:
        metadata=re.findall(r'^AUDIO_BOARD_FILE bytes=(\d+) path='+re.escape(board)+r'$',text,re.M)
        sums=re.findall(r'^([0-9a-f]{64})  '+re.escape(board)+r'$',text,re.M)
        blocks=re.findall(r'^AUDIO_EXPORT_BEGIN path='+re.escape(board)+r' encoding=base64\n([A-Za-z0-9+/=\n]*)\nAUDIO_EXPORT_END path='+re.escape(board)+r'$',text,re.M)
        assert len(metadata)==len(sums)==len(blocks)==1,(key,len(metadata),len(sums),len(blocks))
        encoded=blocks[0].replace('\n','')
        data=base64.b64decode(encoded,validate=True)
        assert base64.b64encode(data).decode()==encoded
        assert len(data)==int(metadata[0]) and hashlib.sha256(data).hexdigest()==sums[0],(key,len(data),metadata,sums)
        host=out/key
        assert not host.exists()
        payloads[host]=data
        records[key]={'board_path':board,'host_path':host.relative_to(ROOT).as_posix(),'bytes':len(data),'sha256':sums[0], 'metadata_raw_path':raw_path.relative_to(ROOT).as_posix(),'transfer_raw_paths':[raw_path.relative_to(ROOT).as_posix()]}
    record={'files':records,'raw':{'path':raw_path.relative_to(ROOT).as_posix(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'no_missing_bytes_inferred_or_padded':True}
    receipt=out/(a.label+'-extraction.json')
    assert not receipt.exists()
    for path,data in payloads.items(): save(path,data)
    save(receipt,(json.dumps(record,indent=2)+'\n').encode())
    print(json.dumps({'exported':a.label,'files':len(records),'bytes':sum(x['bytes'] for x in records.values()),'receipt':receipt.relative_to(ROOT).as_posix()}))
if __name__=='__main__': main()
