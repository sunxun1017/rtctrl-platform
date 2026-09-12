import os, sys, json, time, signal, subprocess
from pathlib import Path
sys.path.insert(0, '/userdata/rtctrl-video-preview')
import benchmark

base = Path('/userdata/rtctrl-video-preview')
out = base / 'reuse-test' / ('repeat-' + str(int(time.time())))
out.mkdir()
trace = Path('/sys/kernel/debug/tracing/instances/mpp_reuse_trial')
trace.mkdir()
def write(name, value):
    (trace/name).write_text(value)
write('tracing_on', '0')
write('set_ftrace_filter', 'system_heap_do_allocate.constprop.0\nsystem_heap_dma_buf_release\n')
write('current_tracer', 'function')
original_cpu = benchmark.cpu_seconds
results = []
try:
    pid = int((base/'preview.pid').read_text())
    assert Path('/proc/%d/cwd' % pid).resolve() == base
    assert b'preview.py' in Path('/proc/%d/cmdline' % pid).read_bytes()
    os.kill(pid, signal.SIGTERM)
    time.sleep(4)
    for label, reuse in [('off-1', '0'), ('on-1', '1'), ('on-2', '1'), ('off-2', '0')]:
        directory = out / label
        directory.mkdir()
        if reuse is None:
            for key in ('GST_PLUGIN_PATH', 'GST_REGISTRY', 'RTCTRL_MPP_REUSE'):
                os.environ.pop(key, None)
        else:
            os.environ.update(GST_PLUGIN_PATH=str(base/'reuse-test/plugins'),
                              GST_REGISTRY=str(base/'reuse-test/registry.bin'), RTCTRL_MPP_REUSE=reuse)
        calls = [0]
        perf = []
        def measured_cpu(pids):
            value = original_cpu(pids)
            if calls[0] == 0:
                write('trace', '')
                write('tracing_on', '1')
                (directory/'pids.json').write_text(json.dumps(pids))
                for pid in pids:
                    (directory/('maps-%d.txt'%pid)).write_text(Path('/proc/%d/maps'%pid).read_text())
                log=(directory/'perf-record.log').open('w')
                perf.append(subprocess.Popen(['perf','record','-e','cpu-clock','-F','99','-g','-p',','.join(map(str,pids)),'-o',str(directory/'perf.data'),'--','sleep','20'],stdout=log,stderr=log))
                log.close()
            else:
                write('tracing_on', '0')
                (directory/'buffers.trace').write_text((trace/'trace').read_text())
            calls[0] += 1
            return value
        benchmark.cpu_seconds = measured_cpu
        result = benchmark.run('hardware', 20, directory)
        for process in perf:
            process.wait(timeout=5)
        with (directory/'perf-self.txt').open('w') as log:
            subprocess.run(['perf','report','--stdio','--no-children','-g','none','-i',str(directory/'perf.data')],stdout=log,stderr=subprocess.STDOUT)
        with (directory/'perf-callgraph.txt').open('w') as log:
            subprocess.run(['perf','report','--stdio','--children','-i',str(directory/'perf.data')],stdout=log,stderr=subprocess.STDOUT)
        data = (directory/'buffers.trace').read_text()
        result.update(label=label, allocations=data.count(': system_heap_do_allocate'),
                      releases=data.count(': system_heap_dma_buf_release'))
        results.append(result)
        (out/'results.json').write_text(json.dumps(results, indent=2))
        print(json.dumps(result), flush=True)
finally:
    write('tracing_on', '0')
    write('current_tracer', 'nop')
    trace.rmdir()
    for key in ('GST_PLUGIN_PATH', 'GST_REGISTRY', 'RTCTRL_MPP_REUSE'):
        os.environ.pop(key, None)
    with (base/'server.log').open('a') as log:
        process = subprocess.Popen([sys.executable, 'preview.py'], cwd=base,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    (base/'preview.pid').write_text(str(process.pid)+'\n')
    print('RESTORED', process.pid, 'RESULTS', out, flush=True)
