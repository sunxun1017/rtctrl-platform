import json, os, signal, subprocess, sys, time, types
from pathlib import Path
base=Path('/userdata/rtctrl-video-preview')
out=base/'reuse-test'/('clean-'+str(int(time.time())))
out.mkdir()
source=(base/'benchmark.py').read_text()
start=source.index('    env = dict(os.environ, GST_TRACERS=')
end=source.index('    with (directory',start)
source=source[:start]+'    env = dict(os.environ)\n'+source[end:]
source=source.replace('    result.update(latency_summary(trace))','    # Latency tracer disabled for CPU comparison.')
module=types.ModuleType('clean_benchmark')
module.__file__=str(base/'benchmark.py')
exec(compile(source,module.__file__,'exec'),module.__dict__)
results=[]
pid=int((base/'preview.pid').read_text())
assert Path('/proc/%d/cwd'%pid).resolve()==base
assert b'preview.py' in Path('/proc/%d/cmdline'%pid).read_bytes()
os.kill(pid,signal.SIGTERM)
time.sleep(3)
try:
    for key in ('GST_TRACERS','GST_DEBUG','GST_DEBUG_FILE'):
        os.environ.pop(key,None)
    os.environ.update(GST_PLUGIN_PATH=str(base/'reuse-test/probe-plugins'),GST_REGISTRY=str(base/'reuse-test/probe-registry.bin'))
    for label, reuse in [('off-1','0'),('on-1','1'),('on-2','1'),('off-2','0'),('off-3','0'),('on-3','1')]:
        os.environ['RTCTRL_MPP_REUSE']=reuse
        directory=out/label
        directory.mkdir()
        result=module.run('hardware',20,directory)
        result['label']=label
        result['cpu_ms_per_frame']=10*result['cpu_percent_one_core']/result['fps']
        results.append(result)
        (out/'results.json').write_text(json.dumps(results,indent=2))
finally:
    for key in ('GST_PLUGIN_PATH','GST_REGISTRY','RTCTRL_MPP_REUSE'):
        os.environ.pop(key,None)
    with (base/'server.log').open('a') as log:
        p=subprocess.Popen(['python3','preview.py'],cwd=base,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    (base/'preview.pid').write_text(str(p.pid)+'\n')
    print('RESTORED',p.pid,'RESULTS',out,flush=True)
