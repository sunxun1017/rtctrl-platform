import os,time,json,re,fcntl,struct
from pathlib import Path
d=Path('/userdata/rtctrl-face-video/cpu50-test');pid=int(Path('/userdata/rtctrl-face-video/video.pid').read_text())
tids={int(x.name) for x in Path('/proc',str(pid),'task').iterdir()}
t=Path('/sys/kernel/debug/tracing/instances/rtctrl_cpu50_alloc_check');t.mkdir()
functions=['system_heap_do_allocate.constprop.0','system_heap_dma_buf_release','rockchip_gem_create_object','rockchip_gem_free_object']
def put(name,value):(t/name).write_text(value)
try:
    put('tracing_on','0');put('set_ftrace_filter','\n'.join(functions));put('current_tracer','function');put('trace','');put('tracing_on','1')
    start=time.monotonic();time.sleep(20);elapsed=time.monotonic()-start
    # One labelled control allocation validates tracing independently of the app.
    heap=os.open('/dev/dma_heap/system-uncached',os.O_RDWR|os.O_CLOEXEC)
    try:
        data=bytearray(struct.pack('QIIQ',4096,0,os.O_RDWR|os.O_CLOEXEC,0))
        fcntl.ioctl(heap,(3<<30)|(24<<16)|(ord('H')<<8),data,True)
        os.close(struct.unpack('QIIQ',data)[1])
    finally:os.close(heap)
    put('tracing_on','0');trace=(t/'trace').read_text();(d/'allocation-trace.txt').write_text(trace)
    counts={x:0 for x in functions};control={x:0 for x in functions};other={x:0 for x in functions}
    for line in trace.splitlines():
        m=re.search(r'-(\d+)\s+\[',line)
        if not m:continue
        dest=counts if int(m[1]) in tids else control if int(m[1])==os.getpid() else other
        for fn in functions:
            if ': '+fn+' ' in line:dest[fn]+=1
    result={'application_pid':pid,'application_tids':sorted(tids),'steady_window_s':elapsed,'application_calls':counts,'control_pid':os.getpid(),'control_calls':control,'other_calls':other,'header':trace.splitlines()[:12]}
    (d/'allocation-summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
finally:
    put('tracing_on','0');put('current_tracer','nop');t.rmdir()
