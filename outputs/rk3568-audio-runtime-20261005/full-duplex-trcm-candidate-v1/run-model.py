#!/usr/bin/env python3
"""Private params candidate, actual finite body identity before/after every run."""
import argparse, hashlib, json, re, stat, subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]
SOURCE=ROOT/'.deps/kernel-source/aiot-3568pq-audio-v4'
IMAGE=HERE.parent/'build/integration-v4/integrated-source-inventory.json'
def sha(data): return hashlib.sha256(data).hexdigest()
def ordinary(p):
    if not p.is_relative_to(ROOT) or not stat.S_ISREG(p.lstat().st_mode): raise ValueError('Ordinary input required '+str(p))
    for parent in p.parents:
        if not stat.S_ISDIR(parent.lstat().st_mode): raise ValueError('Nonordinary ancestor')
        if parent==ROOT: break
    return p
def extract(text,name,digest):
    for prefix in [r'^[A-Za-z_][A-Za-z_0-9 \t*]*\b',r'^[A-Za-z_][A-Za-z_0-9 \t*\n]*\b']:
        for m in re.finditer(prefix+re.escape(name)+r'\([^;{}]*?\)\s*\{',text,re.M):
            depth=0
            for i in range(text.index('{',m.start()),len(text)):
                depth+=(text[i]=='{')-(text[i]=='}')
                if not depth:
                    body=text[m.start():i+1]
                    if sha(body.encode())==digest: return body
                    break
    raise ValueError('Production lexical body drift '+name)
def check(model,manifest):
    actual={p.relative_to(model).as_posix():sha(ordinary(p).read_bytes()) for p in model.rglob('*') if p.is_file() and p.name!='input-manifest.json'}
    if actual!=manifest['model_files_sha256']: raise ValueError('Exact model set/bytes drift')
    if sha(ordinary(IMAGE).read_bytes())!=manifest['Image_source_inventory_sha256']: raise ValueError('Image inventory drift')
    image=json.loads(IMAGE.read_text())
    sm_path=HERE.parent/'full-duplex-params-candidate-v1/source-manifest-v4.json'
    if sha(ordinary(sm_path).read_bytes())!=manifest['parent_source_manifest_sha256']: raise ValueError('Private params manifest drift')
    if sha(ordinary(HERE/'source-manifest-v2.json').read_bytes())!=manifest['CPU_manifest_sha256']:raise ValueError('CPU manifest drift')
    records={}; texts={}
    for rel in sorted({k.split(':')[0] for k in manifest['production_bodies']}|set(manifest['source_locks'])):
        original=ordinary(SOURCE/rel); b=original.read_bytes()
        meta={'bytes':len(b),'mode':'100755' if original.stat().st_mode & stat.S_IXUSR else '100644','sha256':sha(b)}
        if image[rel]!=meta: raise ValueError('Finite actual source/Image drift '+rel)
        records['actual_SOURCE/'+rel]=meta
        if rel in manifest['source_locks']:
            private=ordinary(ROOT/manifest['source_paths'][rel]); data=private.read_bytes()
            if sha(data)!=manifest['source_locks'][rel]: raise ValueError('Private source drift '+rel)
            records['private/'+rel]={'bytes':len(data),'sha256':sha(data)}; texts[rel]=data.decode()
        else: texts[rel]=b.decode()
    for key,item in manifest['production_bodies'].items():
        rel,name=key.split(':',1); body=extract(texts[rel],name,item['sha256'])
        if (model/item['unit']).read_text().count(body)!=1: raise ValueError('Real body absent/duplicate in model '+key)
    n=manifest['native_outer_boundary']; p=ordinary(SOURCE/n['actual_file']); data=p.read_bytes()
    meta={'bytes':len(data),'sha256':sha(data),'mode':'100755' if p.stat().st_mode & stat.S_IXUSR else '100644'}
    if meta!=image[n['actual_file']] or meta!={'bytes':n['bytes'],'sha256':n['sha256'],'mode':n['git_mode']}: raise ValueError('Native outer reference drift')
    records['actual_SOURCE/'+n['actual_file']]=meta
    return records
def expected(model):
    # Literal fixed execution schedule; these are observation rows, not unique tests.
    p=(model/'test-shared-params.c').read_text(); trcm=(model/'test-trcm.c').read_text()
    def labels(text,name):
        m=re.search(r'static (?:void|bool) '+name+r'\([^;]*?\)\s*\{',text)
        depth=0
        for i in range(text.index('{',m.start()),len(text)):
            depth+=(text[i]=='{')-(text[i]=='}')
            if not depth: body=text[m.start():i+1];break
        return re.findall(r'boundary\("([^"]+)"',body)
    setup=labels(p,'shared_setup'); rows=[]
    for d in range(2):
        for name in ['shared_peer_failure','shared_peer_failure','shared_two_free','shared_running']:
            rows+=setup+labels(p,name)
    trcm_setup=setup+labels(trcm,'trcm_setup')
    for name in ['trcm_seq','trcm_seq','trcm_concurrent','trcm_joint','trcm_ticket_window']:
        rows+=trcm_setup+labels(trcm,name)
    # rollback function explicitly resets twice, so its setup observations interleave.
    rollback=labels(trcm,'trcm_admission_and_rollback')
    rows+=trcm_setup+rollback[:1]+trcm_setup+rollback[1:]
    rows+=trcm_setup+labels(trcm,'trcm_native_window')
    if len(rows)!=72:raise ValueError('Fixed 72 observation schedule differs '+str(len(rows)))
    contracts=[]; cases=[]
    for d in range(2):
        contracts += [f'peer_{d}_CPU_error_preserves_configured_DAI_rate',f'peer_{d}_component_error_preserves_configured_DAI_rate',
            f'two_HW_FREE_then_close_first_{d}_clears_configuration_cache',f'running_peer_{d}_after_component_error_rejects_before_shared_mutation']
        cases += contracts[-4:]
    contracts += ['sequential_first_0_second_normal_START','sequential_first_1_second_normal_START',
        'concurrent_two_normal_START_commit_both','shared_fault_joint_STOP_reaches_global_proof']
    cases += ['sequential_first_0_second_normal_START','sequential_first_1_second_normal_START',
        'TRCM_concurrent_START_observations_only','TRCM_shared_status_IO_error','TRCM_fault_during_GO_API',
        'TRCM_CPU_commit_IO_error','TRCM_reservation_and_stale_commit','TRCM_native_post_IRQ_observations_only']
    return rows,contracts,cases
def observe(stdout,expected_rows,expected_contracts,expected_cases):
    rows=[]; contracts=[]; transcripts={}; declared={}; current=None
    for line in stdout.splitlines()[:-1]:
        if line.startswith('BOUNDARY_CHECK '):
            _,n,v=line.split(); rows.append((n,int(v)))
        elif line.startswith('CONTRACT_CHECK '):
            _,n,v=line.split(); contracts.append((n,int(v)))
        elif line.startswith('PARAM_CASE '):
            _,n,count=line.split()
            if n in transcripts: raise ValueError('Duplicate case')
            transcripts[n]=[];declared[n]=int(count);current=n
        elif line.startswith('PARAM_EVENT '):
            _,case,seq,name,value,result=line.split()
            if case!=current or int(seq)!=len(transcripts[case]): raise ValueError('Case/sequence mismatch')
            transcripts[case].append({'name':name,'value':int(value),'result':int(result)})
        else: raise ValueError('Unexpected stdout')
    counts={'contract_total':len(contracts),'contract_passed':sum(v for _,v in contracts),
        'boundary_total':len(rows),'boundary_passed':sum(v for _,v in rows)}
    if json.loads(stdout.splitlines()[-1])!=counts: raise ValueError('Summary does not match actual rows')
    if [n for n,_ in rows]!=expected_rows or [n for n,_ in contracts]!=expected_contracts: raise ValueError('Complete ordered assertion labels differ')
    if list(transcripts)!=expected_cases or any(len(v)!=declared[k] for k,v in transcripts.items()): raise ValueError('Complete ordered case schedule/count differs')
    valid=counts=={'contract_total':12,'contract_passed':12,'boundary_total':72,'boundary_passed':72}
    valid &= [v for _,v in contracts]==[1]*12 and all(v==1 for _,v in rows)
    return {'valid':bool(valid),'baseline_red_scope': [v for _,v in contracts]==[1]*8+[0]*4,'counts':counts,'remaining_reds':[n for n,v in contracts if not v],
        'boundary_failures':[n for n,v in rows if not v],'ordered_boundaries':[n for n,_ in rows],
        'case_transcripts':transcripts,'unique_boundary_labels':len(set(n for n,_ in rows))}
def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--attempt',required=True);p.add_argument('--check',action='store_true');args=p.parse_args()
    if not re.fullmatch(r'model-v[2-9][0-9]*',args.model) or not re.fullmatch(r'[a-z0-9]+',args.attempt): raise ValueError('Version/fresh attempt required')
    model=HERE/args.model; mb=ordinary(model/'input-manifest.json').read_bytes()
    if sha(mb)!=args.manifest_sha256: raise ValueError('Reviewed manifest SHA differs')
    manifest=json.loads(mb); initial=check(model,manifest); expected_rows,expected_contracts,expected_cases=expected(model)
    if args.check:
        print(json.dumps({'status':'READONLY_SOURCE_MODEL_PRECHECK','finite_actual_SOURCE_files':sum(k.startswith('actual_SOURCE/') for k in initial),
            'private_source_files':sum(k.startswith('private/') for k in initial),'available_actual_bodies':len(manifest['production_bodies']),
            'fixed_contracts':12,'fixed_boundary_observations':72,'ordered_case_groups':len(expected_cases),'compiler_executed':False}));return 0
    out=HERE/('runs-'+args.attempt);out.mkdir()
    (out/'runner-snapshot.py').write_bytes(Path(__file__).read_bytes());(out/'input-manifest.json').write_bytes(mb)
    receipt={'scope':'PRIVATE_CALLER_MODEL_NOT_KERNEL_OR_HARDWARE','runner_sha256':sha(Path(__file__).read_bytes()),
        'manifest_sha256':sha(mb),'inputs_before':initial,'model_runs':{},'fixed_counts':{'contract_total':12,'contract_passed':12 if manifest['candidate'] else 8,'boundary_total':72,'boundary_passed':72 if manifest['candidate'] else None},
        'ordered_expected_boundaries':expected_rows,'ordered_expected_contracts':expected_contracts,
        'ordered_expected_case_groups':expected_cases,'Kbuild_executed':False,'board_tested':False,'duplex_START_authorized':False}
    def save(): (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def command(argv,name):
        argv=list(map(str,argv));r=subprocess.run(argv,capture_output=True,timeout=45)
        (out/(name+'.stdout')).write_bytes(r.stdout);(out/(name+'.stderr')).write_bytes(r.stderr)
        rec={'argv':argv,'exit':r.returncode,'stdout_bytes':len(r.stdout),'stdout_sha256':sha(r.stdout),'stderr_bytes':len(r.stderr),'stderr_sha256':sha(r.stderr)}
        (out/(name+'.command.json')).write_text(json.dumps(rec,indent=2)+'\n');return r,rec
    failed=False; stdouts=[]
    for label,compiler,flags,prefix in [('host','gcc',[],[]),('asan-ubsan','gcc',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie'],[]),
        ('aarch64-qemu','aarch64-linux-gnu-gcc',['-static'],[ROOT/'.deps/qemu-user/root/usr/bin/qemu-aarch64-static'])]:
        binary=out/('params-'+label)
        r,rec=command([compiler,'-std=gnu11','-O0','-finstrument-functions','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function','-Wno-sign-compare','-pthread',*flags,model/'unit.c','-o',binary],label+'-compile')
        record={'compile':rec};failed|=r.returncode!=0
        if not r.returncode:
            r,rec=command([*prefix,binary],label+'-execute');record.update({'execution':rec,'binary_sha256':sha(binary.read_bytes())})
            stdouts.append(r.stdout)
            try:
                ob=observe(r.stdout.decode(),expected_rows,expected_contracts,expected_cases);record['observation']=ob
                valid=(ob['valid'] and r.returncode==0 if manifest['candidate'] else ob['baseline_red_scope'] and r.returncode==1) and not r.stderr
            except (ValueError,IndexError,KeyError) as e: valid=False;record['observation_error']=str(e)
            record['expected_scope_verified']=valid;failed|=not valid
        receipt['model_runs'][label]=record;save()
    receipt['inputs_after']=check(model,manifest)
    receipt['all_three_full_stdout_bytes_equal']=len(stdouts)==3 and len(set(stdouts))==1
    failed|=receipt['inputs_after']!=initial or not receipt['all_three_full_stdout_bytes_equal']
    if sha(Path(__file__).read_bytes())!=receipt['runner_sha256']: raise ValueError('Runner drift')
    receipt['status']='UNEXPECTED_MODEL_OR_COMPILER_FAILURE' if failed else ('FINITE_CPU_TRCM_MODEL_GREEN_NOT_PL330_OR_BOARD' if manifest['candidate'] else 'FOUR_REAL_CPU_TRCM_BASELINE_REDS_RETAINED');save()
    print(json.dumps({'status':receipt['status'],'runs':{k:{'compile':v['compile']['exit'],'execution':v.get('execution',{}).get('exit'),'counts':v.get('observation',{}).get('counts'),'error':v.get('observation_error')} for k,v in receipt['model_runs'].items()},
        'full_stdout_equal':receipt['all_three_full_stdout_bytes_equal']}));return int(failed)
if __name__=='__main__': raise SystemExit(main())
