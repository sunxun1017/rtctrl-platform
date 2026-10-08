#!/usr/bin/env python3
"""Finite final evidence readback and private four-file patch application."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]

def sha(b):
    return hashlib.sha256(b).hexdigest()

source_manifest=json.loads((HERE/'source-manifest-v5.json').read_text())
record={'source_version':'source-v5','source_manifest_sha256':sha((HERE/'source-manifest-v5.json').read_bytes()),
        'patch_sha256':sha((HERE/'dma-fault-private-v5.patch').read_bytes()),
        'runner_sha256':sha((HERE/'run-model.py').read_bytes()),'sources':{},'actual_model_receipts':{}}
for name,meta in source_manifest.items():
    data=(HERE/'source-v5'/name).read_bytes()
    if {'bytes':len(data),'sha256':sha(data)}!=meta or b'\r' in data or data.startswith(b'\xef\xbb\xbf'):
        raise ValueError('Source bytes/line endings drift')
    record['sources'][name]=meta
fixed_rows=None
for folder,expected_failures in [('runs-red-v7',28),('runs-sync-red-v1',1),('runs-green-v7',0)]:
    where=HERE/folder
    receipt=json.loads((where/'receipt.json').read_text())
    stdouts=[]
    for label in ['host','asan-ubsan','aarch64-qemu']:
        run=receipt['runs'][label]
        stdout=(where/(label+'-execute.stdout')).read_bytes()
        stderr=(where/(label+'-execute.stderr')).read_bytes()
        if run['compile']['exit'] or run['execute']['exit']!=(bool(expected_failures)) or stderr:
            raise ValueError('Actual command failed expected scope')
        if sha(stdout)!=run['execute']['stdout_sha256'] or sha(stderr)!=run['execute']['stderr_sha256']:
            raise ValueError('Transcript drift')
        rows=re.findall(r'^OBS (\S+) ([01])$',stdout.decode(),re.M)
        if len(rows)!=37 or sum(v=='0' for _,v in rows)!=expected_failures:
            raise ValueError('Fixed 37 observations differ')
        names=[n for n,_ in rows]
        if fixed_rows is None:
            fixed_rows=names
        if fixed_rows!=names:
            raise ValueError('Ordered observation labels differ')
        if folder=='runs-green-v7' and any(v!='1' for _,v in rows):
            raise ValueError('Candidate observation failed')
        stdouts.append(stdout)
    if len(set(stdouts))!=1 or not receipt['source_unchanged'] or receipt['actual_SDK_inputs_before']!=receipt['actual_SDK_inputs_after']:
        raise ValueError('Actual finite before/after/transcripts drift')
    record['actual_model_receipts'][folder]={'sha256':sha((where/'receipt.json').read_bytes()),
        'observations':37,'passed':37-expected_failures,'complete_stdout_sha256':sha(stdouts[0])}
record['ordered_observations']=fixed_rows
record['model_boundaries']=['MMIO/PM/ALSA state/CPU fault hook are API leaves',
    'PL330 terminate_channel leaf supplies existing cutoff+epoch behaviour; full real sync/drain body executed',
    'generic PCM open/close and runtime hw-constraint leaves are API fixtures; actual generic binding bodies executed',
    'quarantine real metadata transfer executed; model cleanup explicitly represents later power-cycle, not driver recovery',
    'body identities are not instrumentation coverage or kernel ABI proof']
check=HERE/'patch-check-v2'
check.mkdir()
for name in source_manifest:
    target=check/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes((HERE/'baseline'/name).read_bytes())
patch=HERE/'dma-fault-private-v5.patch'
record['patch_commands']=[]
for label,flags in [('check',['--check']),('apply',[])]:
    argv=['git','apply',*flags,'--unsafe-paths','--directory='+str(check),str(patch)]
    result=subprocess.run(argv,capture_output=True,timeout=20,cwd=ROOT)
    (HERE/('patch-v2-'+label+'.stdout')).write_bytes(result.stdout)
    (HERE/('patch-v2-'+label+'.stderr')).write_bytes(result.stderr)
    command={'argv':argv,'exit':result.returncode,'stdout_sha256':sha(result.stdout),'stderr_sha256':sha(result.stderr)}
    (HERE/('patch-v2-'+label+'.command.json')).write_text(json.dumps(command,indent=2)+'\n')
    record['patch_commands'].append(command)
    if result.returncode:
        raise ValueError('Private patch '+label+' failed')
record['patch_result_equals_candidate']=all((check/name).read_bytes()==(HERE/'source-v5'/name).read_bytes() for name in source_manifest)
if not record['patch_result_equals_candidate']:
    raise ValueError('Private actual apply mismatch')
header=ROOT/'outputs/rk3568-audio-runtime-20261005/full-duplex-params-candidate-v1/source-v4/include/sound/soc-dai.h'
data=header.read_bytes()
old=b'\tvoid (*hw_params_fault)(struct snd_soc_dai *, int first_errno);\n'
if data.count(old)!=1:
    raise ValueError('Header hook anchor differs')
record['header_base_sha256']=sha(data)
hook='''--- a/include/sound/soc-dai.h
+++ b/include/sound/soc-dai.h
@@ -307,1 +307,4 @@
 	void (*hw_params_fault)(struct snd_soc_dai *, int first_errno);
+	/* CPU-only atomic fault admission: no sleeping or codec callbacks. */
+	void (*pcm_async_fault)(struct snd_soc_dai *, int first_errno);
+
'''
(HERE/'soc-dai-async-hook.patch').write_text(hook)
record['header_hook_patch_sha256']=sha((HERE/'soc-dai-async-hook.patch').read_bytes())
record['Kbuild_executed']=False
record['board_tested']=False
record['duplex_START_authorized']=False
record['actual_SDK_modified']=False
(HERE/'review-ready-v2.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'final_source':'source-v5','final_green':37,'old_red_passed':9,'private_apply_equal':True}))
