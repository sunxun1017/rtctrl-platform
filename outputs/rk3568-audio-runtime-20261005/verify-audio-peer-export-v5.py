#!/usr/bin/env python3
"""Verify full original peer files and its strict pre/post guards, offline only."""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--open-first',choices=['playback','capture'],required=True)
p.add_argument('--close-first',choices=['playback','capture'],required=True)
a=p.parse_args()
label=f'peer-idle-open-{a.open_first}-close-{a.close_first}-v5'
folder=HERE/'build/board-exports-v5'
tool=HERE/'prepare-live-audio-steps-v5.py'
assert hashlib.sha256(tool.read_bytes()).hexdigest()=='80baf3482cb90e7fd5d78b9ef3ff064c50e6cdede7991e63a3d328de06bba85b'
inputs={}
for name in ['pre-'+label,label,'post-'+label]:
 for ext in ['stdout','stderr','exit']:
  path=folder/(name+'.'+ext);data=path.read_bytes()
  inputs[path.relative_to(ROOT).as_posix()]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
 if name!=label:
  assert (folder/(name+'.exit')).read_bytes()==b'0\n'
  assert (folder/(name+'.stderr')).read_bytes()==b''
  text=(folder/(name+'.stdout')).read_text()
  assert text.count('AUDIO_SESSION_IDLE_VERIFIED stage=bound allocated=2 board_start_permission=0 reboot_permission=0')==1
  assert text.count('AUDIO_CPU version=1 ready=1 error=0 owners=0 open=0 stop_proven=1')==1
  assert 'queued=0 descriptors=0 allocated=2' in text and 'AUDIO_QUARANTINE 0\n' in text
argv=[sys.executable,'-B',str(tool),'--verify-peer-stdout',str(folder/(label+'.stdout')),'--peer-stderr',str(folder/(label+'.stderr')),'--peer-exit',str(folder/(label+'.exit')),'--open-first',a.open_first,'--close-first',a.close_first]
r=subprocess.run(argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
assert hashlib.sha256(tool.read_bytes()).hexdigest()=='80baf3482cb90e7fd5d78b9ef3ff064c50e6cdede7991e63a3d328de06bba85b'
assert r.returncode==0 and r.stderr==b'',r.stderr
result=json.loads(r.stdout)
assert result['complete_operations']==34 and result['process_exit']==0 and result['first_error'] is None
for name,entry in inputs.items():
 data=(ROOT/name).read_bytes();assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256']
out=HERE/'build/board-exports-v5'/(label+'-verification.json')
obj={'full_original_inputs':inputs,'peer_parser_sha256':'80baf3482cb90e7fd5d78b9ef3ff064c50e6cdede7991e63a3d328de06bba85b','actual_parser_argv':argv,'actual_parser_exit':r.returncode,'actual_parser_stdout_sha256':hashlib.sha256(r.stdout).hexdigest(),'actual_parser_stderr_bytes':len(r.stderr),'peer_result':result,'pre_post_strict_guard_original_exit0_stderr_empty':True,'kernel_diagnostics_requires_separate_original_evidence':True,'board_START_authorized':False,'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
with out.open('x',newline='\n') as f:f.write(json.dumps(obj,indent=2)+'\n')
print(json.dumps({'peer':label,'complete_operations':34,'pre_post_guard':'verified original exit0/stderr empty','hardware_START_permission':False}))
