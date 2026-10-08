#!/usr/bin/env python3
"""Root operator finite metadata-to-export adapter, no device I/O."""
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PRIVATE=ROOT/'outputs/rk3568-pid1-20261005/private'
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('action',choices=['prepare','extract'])
 p.add_argument('--label',required=True)
 p.add_argument('--metadata-raw',required=True)
 p.add_argument('--raw-name',action='append',required=True)
 p.add_argument('--expected-files',type=int,required=True)
 a=p.parse_args()
 assert re.fullmatch('[a-z0-9-]{1,90}',a.label)
 assert re.fullmatch('[a-z0-9.-]{1,120}',a.metadata_raw)
 tool=HERE/'export-board-files-v5-r2.py'
 assert hashlib.sha256(tool.read_bytes()).hexdigest()=='71b655dcbb064693ed050a0ab84e8e48eea6e89e4f2cb452ec5c433d416207b0'
 raw=(PRIVATE/a.metadata_raw).read_bytes();text=raw.decode('ascii').replace('\r','')
 metas=re.findall(r'^AUDIO_BOARD_FILE bytes=(\d+) path=(/tmp/audio/[a-zA-Z0-9._-]+)$',text,re.M)
 assert len(metas)==a.expected_files and len(set(b for n,b in metas))==len(metas)
 argv=[sys.executable,'-B',str(tool),a.action,'--label',a.label]
 files={}
 for n,board in metas:
  sums=re.findall(r'^([0-9a-f]{64})  '+re.escape(board)+r'$',text,re.M)
  assert len(sums)==1
  key=board.rsplit('/',1)[1]
  argv+=['--file',f'{key}={board}:{n}:{sums[0]}']
  files[key]={'bytes':int(n),'sha256':sums[0],'board_path':board}
 for name in a.raw_name:argv+=['--raw-name',name]
 specs=HERE/'build/board-exports-v5'/(a.label+'-specs.json')
 if a.action=='prepare':
  with specs.open('x',newline='\n') as f:f.write(json.dumps({'metadata_raw_path':(PRIVATE/a.metadata_raw).relative_to(ROOT).as_posix(),'metadata_raw_sha256':hashlib.sha256(raw).hexdigest(),'files':files,'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2)+'\n')
 else:
  saved=json.loads(specs.read_text());assert saved['files']==files and saved['metadata_raw_sha256']==hashlib.sha256(raw).hexdigest()
 result=subprocess.run(argv,cwd=ROOT,check=False)
 raise SystemExit(result.returncode)
if __name__=='__main__':main()
