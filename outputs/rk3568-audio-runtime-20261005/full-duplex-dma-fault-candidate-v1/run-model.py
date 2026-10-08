#!/usr/bin/env python3
"""Extract finite real bodies, compile/run three environments, keep each attempt."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

def sha(b):
    return hashlib.sha256(b).hexdigest()

def function(s, n):
    m = re.search(r'^[A-Za-z_][A-Za-z_0-9 \t*\n]*\b' + re.escape(n) + r'\([^;{}]*?\)\s*\{', s, re.M)
    if not m:
        raise ValueError('Missing real function ' + n)
    depth = 0
    for i in range(s.index('{', m.start()), len(s)):
        depth += (s[i] == '{') - (s[i] == '}')
        if not depth:
            return s[m.start():i + 1]
    raise ValueError('Unclosed real body')

def declaration(s,n):
    m = re.search(r'^struct ' + n + r'\s*\{',s,re.M)
    return s[m.start():s.index('\n};',m.end())+3]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',choices=['baseline','source-v1','source-v2','source-v3','source-v4','source-v5'],required=True)
    parser.add_argument('--attempt',required=True)
    a=parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9-]*',a.attempt):
        raise ValueError('Safe new attempt name')
    out=HERE/('runs-'+a.attempt)
    out.mkdir()
    src=HERE/a.source
    baseline=json.loads((HERE/'baseline-manifest.json').read_text())
    actual_sdk=ROOT/'.deps/kernel-source/aiot-3568pq-audio-v4'
    def actual_inputs():
        result={}
        for name,meta in baseline.items():
            data=(actual_sdk/name).read_bytes()
            record={'bytes':len(data),'sha256':sha(data)}
            if record!=meta or (HERE/'baseline'/name).read_bytes()!=data:
                raise ValueError('Finite SDK/baseline drift: '+name)
            result[name]=record
        return result
    before_actual=actual_inputs()
    candidate_manifest=None
    if a.source!='baseline':
        manifest_path=HERE/('source-manifest-'+a.source.split('-')[-1]+'.json')
        candidate_manifest={'sha256':sha(manifest_path.read_bytes()),'files':json.loads(manifest_path.read_text())}
        for name,meta in candidate_manifest['files'].items():
            data=(src/name).read_bytes()
            if {'bytes':len(data),'sha256':sha(data)}!=meta:
                raise ValueError('Candidate manifest drift: '+name)
    texts={p:(src/p).read_text() for p in ['drivers/dma/pl330.c','sound/core/pcm_dmaengine.c','sound/soc/soc-generic-dmaengine-pcm.c','include/sound/dmaengine_pcm.h']}
    memory=(HERE/'baseline/sound/core/pcm_memory.c').read_text()
    private=(HERE/'baseline/drivers/dma/dmaengine.h').read_text()
    pl=texts['drivers/dma/pl330.c']
    engine=texts['sound/core/pcm_dmaengine.c']
    green=a.source!='baseline'
    bodies={}
    def add(s,names,prefix):
        for n in names:
            bodies[prefix+':'+n]=function(s,n)
    add(private,['dmaengine_desc_get_callback','dmaengine_desc_callback_valid','dmaengine_desc_callback_invoke'],'dma-private')
    add(pl,['pl330_error_locked','pl330_desc_get','pl330_desc_put','pl330_software_drained_locked','pl330_software_drained','pl330_capture_stop_locked','pl330_sync_channel','pl330_check_open'],'pl330')
    if green:
        add(pl,['pl330_fault_capture_locked','pl330_fault_notify'],'pl330')
    add(pl,['pl330_dotask'],'pl330')
    add(memory,['snd_pcm_dma_quarantine_alloc','snd_pcm_dma_quarantine_free','snd_pcm_dma_quarantine_bytes','snd_pcm_dma_quarantine_check','snd_pcm_dma_quarantine'],'memory')
    add(engine,['substream_to_prtd','dmaengine_pcm_error','dmaengine_pcm_operation_begin','dmaengine_pcm_operation_end','dmaengine_pcm_dma_complete','snd_dmaengine_pcm_pointer','snd_dmaengine_pcm_pointer_no_residue','snd_dmaengine_pcm_quiesce'],'pcm')
    if green:
        add(engine,['dmaengine_pcm_notify_fault','dmaengine_pcm_check_fault','dmaengine_pcm_dma_complete_result','snd_dmaengine_pcm_set_error_sink'],'pcm')
    add(engine,['dmaengine_pcm_prepare_and_submit','snd_dmaengine_pcm_trigger'],'pcm')
    generic=texts['sound/soc/soc-generic-dmaengine-pcm.c']
    if green:
        add(generic,['dmaengine_pcm_cpu_fault'],'generic')
    add(generic,['dmaengine_pcm_open'],'generic')
    types=declaration(private,'dmaengine_desc_callback')+'\n'+declaration(memory,'snd_pcm_dma_quarantine')+'\n'+declaration(engine,'dmaengine_pcm_runtime_data')+'\n'
    if green:
        types+=declaration(pl,'pl330_fault_callback')+'\n#define PL330_MAX_FAULT_CALLBACKS 8\n'
    globals='static LIST_HEAD(pcm_dma_quarantine);\nstatic DEFINE_MUTEX(pcm_dma_quarantine_lock);\nstatic atomic_long_t pcm_dma_quarantine_bytes=ATOMIC_LONG_INIT(0);\n'
    prototypes='\n'.join(function(s,n).split('{',1)[0]+';' for s,n in [(pl,'pl330_desc_get'),(pl,'pl330_desc_put')])+'\n'
    if green:
        prototypes+='static void dmaengine_pcm_notify_fault(struct snd_pcm_substream *, int, bool);\nstatic int dmaengine_pcm_check_fault(struct snd_pcm_substream *);\n'
    unit='#include "model-shim.h"\n'+types+globals+prototypes+'\n\n'.join(bodies.values())
    unit+='\nstatic int dmaengine_check_open(struct dma_chan *c){return pl330_check_open(c);}\nstatic int dmaengine_synchronize_checked(struct dma_chan *c){return pl330_sync_channel(c,true);}\n'
    unit+=('\n#define CANDIDATE 1\n' if green else '\n#define CANDIDATE 0\n')+'#include "model-main.c"\n'
    (out/'unit.c').write_text(unit)
    for name in ['model-shim.h','model-main.c','run-model.py']:
        (out/name).write_bytes((HERE/name).read_bytes())
    for name,text in texts.items():
        (out/(name.replace('/','-')+'.input')).write_text(text)
    receipt={'source':a.source,'scope':'REAL_NARROW_BODIES_API_LEAF_MODEL_NOT_KERNEL_OR_BOARD',
             'source_sha256':{n:sha((src/n).read_bytes()) for n in texts},
             'available_real_body_identities':{n:sha(t.encode()) for n,t in bodies.items()},
             'identity_count_is_not_execution_coverage':True,
             'actual_SDK_inputs_before':before_actual,'candidate_manifest':candidate_manifest,
             'runs':{},'Kbuild_executed':False,'board_tested':False}
    transcripts=[]
    for label,cc,flags,prefix in [('host','gcc',[],[]),('asan-ubsan','gcc',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie'],[]),('aarch64-qemu','aarch64-linux-gnu-gcc',['-static'],[ROOT/'.deps/qemu-user/root/usr/bin/qemu-aarch64-static'])]:
        binary=out/label
        def call(argv,stem):
            argv=list(map(str,argv))
            r=subprocess.run(argv,capture_output=True,timeout=45)
            (out/(stem+'.stdout')).write_bytes(r.stdout)
            (out/(stem+'.stderr')).write_bytes(r.stderr)
            rec={'argv':argv,'exit':r.returncode,'stdout_sha256':sha(r.stdout),'stderr_sha256':sha(r.stderr),'stdout_bytes':len(r.stdout),'stderr_bytes':len(r.stderr)}
            (out/(stem+'.command.json')).write_text(json.dumps(rec,indent=2)+'\n')
            return r,rec
        r,rec=call([cc,'-std=gnu11','-O0','-Wall','-Wextra','-Werror','-Wno-sign-compare','-Wno-unused-parameter','-Wno-unused-function', '-pthread',*flags,out/'unit.c','-o',binary],label+'-compile')
        entry={'compile':rec}
        if not r.returncode:
            r,rec=call([*prefix,binary],label+'-execute')
            entry['execute']=rec
            transcripts.append(r.stdout)
        receipt['runs'][label]=entry
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    receipt['source_after_sha256']={n:sha((src/n).read_bytes()) for n in texts}
    receipt['actual_SDK_inputs_after']=actual_inputs()
    receipt['three_full_transcripts_equal']=len(transcripts)==3 and len(set(transcripts))==1
    receipt['source_unchanged']=receipt['source_sha256']==receipt['source_after_sha256']
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'receipt':str(out/'receipt.json'),'runs':{n:{k:v['exit'] for k,v in r.items()} for n,r in receipt['runs'].items()},'same':receipt['three_full_transcripts_equal']}))
    return 0 if len(transcripts)==3 else 1

if __name__=='__main__':
    raise SystemExit(main())
