import json,os,signal,subprocess,time,types,re,statistics
from pathlib import Path
base=Path('/userdata/rtctrl-video-preview');out=base/'reuse-test'/('packet-perf-'+str(int(time.time())));out.mkdir()
s=(base/'reuse-test/preview_nv12.py').read_text().replace('"zero-copy-pkt=true"','"zero-copy-pkt=" + os.environ.get("RTCTRL_PACKET_ZERO", "true")')
(base/'reuse-test/preview_memory.py').write_text(s)
source=(base/'benchmark.py').read_text();start=source.index('    env = dict(os.environ, GST_TRACERS=');end=source.index('    with (directory',start)
source=source[:start]+'    env = dict(os.environ)\n'+source[end:]
source=source.replace('str(Path(__file__).with_name("preview.py"))','"/userdata/rtctrl-video-preview/reuse-test/preview_memory.py"')
source=source.replace('    result.update(latency_summary(trace))','    # No detailed tracer')
source=source.replace('            samples.append(sample)','            observe(pids)\n            samples.append(sample)')
m=types.ModuleType('memory_benchmark');m.__file__=str(base/'benchmark.py');exec(compile(source,m.__file__,'exec'),m.__dict__)
def memory(pids):
    pss=rss=0;objects={}
    for pid in pids:
        sm=Path('/proc/%d/smaps_rollup'%pid).read_text()
        pss+=int(re.search(r'^Pss:\s+(\d+)',sm,re.M)[1]);rss+=int(re.search(r'^Rss:\s+(\d+)',sm,re.M)[1])
        for info in Path('/proc/%d/fdinfo'%pid).glob('*'):
            try: fields=dict(line.split(':',1) for line in info.read_text().splitlines() if ':' in line)
            except OSError:continue
            if 'exp_name' in fields:
                objects[fields['ino'].strip()]=dict(size=int(fields['size']),exporter=fields['exp_name'].strip())
    return dict(pss_kb=pss,rss_kb=rss,dma_objects=len(objects),dma_bytes=sum(x['size'] for x in objects.values()),npu=Path('/sys/kernel/debug/rknpu/load').read_text().strip())
pid=int((base/'preview.pid').read_text());assert Path('/proc/%d/cwd'%pid).resolve()==base;assert b'preview.py' in Path('/proc/%d/cmdline'%pid).read_bytes()
os.kill(pid,signal.SIGTERM);time.sleep(3);results=[]
try:
    for key in ('GST_TRACERS','GST_DEBUG','GST_DEBUG_FILE'):os.environ.pop(key,None)
    os.environ.update(GST_PLUGIN_PATH=str(base/'reuse-test/probe-plugins'),GST_REGISTRY=str(base/'reuse-test/probe-registry.bin'),RTCTRL_SINGLE_NV12='1')
    for label,pool,zero in [('zero1','1','true'),('zero0','1','false')]:
        os.environ.update(RTCTRL_MPP_REUSE=pool,RTCTRL_PACKET_ZERO=zero)
        directory=out/label;directory.mkdir();observations=[]
        perf=[]
        def observe(pids):
            observations.append(memory(pids))
            if not perf:
                with (directory/'perf-record.log').open('w') as log:
                    perf.append(subprocess.Popen(['perf','record','-e','cpu-clock','-F','99','-g','-p',','.join(map(str,pids)),'-o',str(directory/'perf.data'),'--','sleep','18'],stdout=log,stderr=log))
        m.observe=observe
        result=m.run('hardware',20,directory);result.update(label=label,cpu_ms_per_frame=10*result['cpu_percent_one_core']/result['fps'])
        for p in perf:p.wait(timeout=5)
        for name,args in [('self',['--no-children','-g','none']),('callgraph',['--children'])]:
            with (directory/('perf-'+name+'.txt')).open('w') as log:
                subprocess.run(['perf','report','--stdio',*args,'-i',str(directory/'perf.data')],stdout=log,stderr=subprocess.STDOUT)
        result['memory']=dict(pss_mean_kb=statistics.mean(x['pss_kb'] for x in observations),pss_min_kb=min(x['pss_kb'] for x in observations),pss_max_kb=max(x['pss_kb'] for x in observations),dma_min_bytes=min(x['dma_bytes'] for x in observations),dma_max_bytes=max(x['dma_bytes'] for x in observations),dma_objects_min=min(x['dma_objects'] for x in observations),dma_objects_max=max(x['dma_objects'] for x in observations),npu_loads=sorted(set(x['npu'] for x in observations)))
        (directory/'memory.json').write_text(json.dumps(observations,indent=2));results.append(result);(out/'results.json').write_text(json.dumps(results,indent=2))
finally:
    for key in ('GST_PLUGIN_PATH','GST_REGISTRY','RTCTRL_MPP_REUSE','RTCTRL_SINGLE_NV12','RTCTRL_PACKET_ZERO'):os.environ.pop(key,None)
    with (base/'server.log').open('a') as log:p=subprocess.Popen(['python3','preview.py'],cwd=base,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    (base/'preview.pid').write_text(str(p.pid)+'\n');print('RESTORED',p.pid,'RESULTS',out,flush=True)
