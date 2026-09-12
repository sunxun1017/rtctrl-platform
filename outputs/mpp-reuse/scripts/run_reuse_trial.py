import os, sys, json, time, signal, subprocess
from pathlib import Path
sys.path.insert(0, '/userdata/rtctrl-video-preview')
import benchmark

base = Path('/userdata/rtctrl-video-preview')
out = base / 'reuse-test' / ('results-' + str(int(time.time())))
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
    for label, reuse in [('system', None), ('rebuilt-off', '0'), ('rebuilt-on', '1')]:
        directory = out / label
        directory.mkdir()
        if reuse is None:
            for key in ('GST_PLUGIN_PATH', 'GST_REGISTRY', 'RTCTRL_MPP_REUSE'):
                os.environ.pop(key, None)
        else:
            os.environ.update(GST_PLUGIN_PATH=str(base/'reuse-test/plugins'),
                              GST_REGISTRY=str(base/'reuse-test/registry.bin'), RTCTRL_MPP_REUSE=reuse)
        calls = [0]
        def measured_cpu(pids):
            value = original_cpu(pids)
            if calls[0] == 0:
                write('trace', '')
                write('tracing_on', '1')
            else:
                write('tracing_on', '0')
                (directory/'buffers.trace').write_text((trace/'trace').read_text())
            calls[0] += 1
            return value
        benchmark.cpu_seconds = measured_cpu
        result = benchmark.run('hardware', 20, directory)
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
