#!/usr/bin/env python3
import argparse, hashlib, json, subprocess
from pathlib import Path
here=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('argv',nargs=argparse.REMAINDER);a=p.parse_args()
if not a.out.replace('-','').isalnum() or not a.argv: raise ValueError('Fresh local output and argv required')
out=here/a.out;out.mkdir()
argv=a.argv[1:] if a.argv[0]=='--' else a.argv
r=subprocess.run(argv,capture_output=True,timeout=60)
(out/'stdout').write_bytes(r.stdout);(out/'stderr').write_bytes(r.stderr)
record={'argv':argv,'exit':r.returncode,'stdout_sha256':hashlib.sha256(r.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(r.stderr).hexdigest()}
(out/'command.json').write_text(json.dumps(record,indent=2)+'\n')
print(r.stdout.decode(),end='');print(r.stderr.decode(),end='')
raise SystemExit(r.returncode)
