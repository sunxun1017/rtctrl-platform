import json, os, signal, subprocess, types, time
from pathlib import Path
base=Path('/userdata/rtctrl-video-preview')
out=base/'parser-test'/('pipeline-'+str(int(time.time())))
out.mkdir()
source=(base/'benchmark.py').read_text()
start=source.index('    env = dict(os.environ, GST_TRACERS=')
end=source.index('    with (directory',start)
source=source[:start]+'    env = dict(os.environ)\n'+source[end:]
source=source.replace('str(Path(__file__).with_name("preview.py"))','str(preview_path)')
source=source.replace('    result.update(latency_summary(trace))','    # No latency tracer.')
m=types.ModuleType('parser_benchmark');m.__file__=str(base/'benchmark.py')
exec(compile(source,m.__file__,'exec'),m.__dict__)
orig=m.cpu_seconds
pid=int((base/'preview.pid').read_text())
assert Path('/proc/%d/cwd'%pid).resolve()==base
assert b'preview.py' in Path('/proc/%d/cmdline'%pid).read_bytes()
os.kill(pid,signal.SIGTERM);time.sleep(3)
results=[]
try:
    for key in ('GST_TRACERS','GST_DEBUG','GST_DEBUG_FILE','GST_PLUGIN_PATH','GST_REGISTRY','RTCTRL_MPP_REUSE'):
        os.environ.pop(key,None)
    for label,variant,profile in [('before-1','before',False),('after-1','after',False),('after-2','after',False),('before-2','before',False),('before-perf','before',True),('after-perf','after',True)]:
        directory=out/label;directory.mkdir()
        m.preview_path=base/'parser-test'/('preview_parser_'+variant+'.py')
        cpu=[];perf=[]
        def record_cpu(pids):
            cpu.append({str(p):orig([p]) for p in pids})
            if len(cpu)==1 and profile:
                with (directory/'perf-record.log').open('w') as log:
                    perf.append(subprocess.Popen(['perf','record','-e','cpu-clock','-F','99','-g','-p',','.join(map(str,pids)),'-o',str(directory/'perf.data'),'--','sleep','20'],stdout=log,stderr=log))
            return sum(cpu[-1].values())
        m.cpu_seconds=record_cpu
        result=m.run('hardware',20,directory)
        result.update(label=label,profile=profile,cpu_ms_per_frame=10*result['cpu_percent_one_core']/result['fps'])
        keys=list(cpu[0])
        result['python_cpu_percent']=100*(cpu[1][keys[0]]-cpu[0][keys[0]])/result['seconds']
        result['gst_cpu_percent']=result['cpu_percent_one_core']-result['python_cpu_percent']
        for p in perf:p.wait(timeout=5)
        if profile:
            with (directory/'perf-self.txt').open('w') as log:
                subprocess.run(['perf','report','--stdio','--no-children','-g','none','-i',str(directory/'perf.data')],stdout=log,stderr=subprocess.STDOUT)
        results.append(result);(out/'results.json').write_text(json.dumps(results,indent=2))
finally:
    with (base/'server.log').open('a') as log:
        p=subprocess.Popen(['python3','preview.py'],cwd=base,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    (base/'preview.pid').write_text(str(p.pid)+'\n')
    print('RESTORED',p.pid,'RESULTS',out,flush=True)
