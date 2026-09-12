import time,json,re,urllib.request,sys
from pathlib import Path
d=Path('/userdata/rtctrl-face-video/ftrace-next');d.mkdir(exist_ok=True)
name=sys.argv[1] if len(sys.argv)>1 else 'baseline'
pid=int(Path('/userdata/rtctrl-face-video/video.pid').read_text());tids=sorted(int(p.name) for p in Path('/proc',str(pid),'task').iterdir())
t=Path('/sys/kernel/debug/tracing/instances/rtctrl_npu_latency');t.mkdir()
functions=['rknpu_submit_ioctl','rknpu_job_schedule','rknpu_core0_irq_handler','rknpu_core1_irq_handler','rknpu_core2_irq_handler','iommu_dma_sync_single_for_device','iommu_dma_sync_single_for_cpu','iommu_dma_sync_sg_for_device','iommu_dma_sync_sg_for_cpu']
def put(p,s):(t/p).write_text(s)
def status():
    s=json.load(urllib.request.urlopen('http://127.0.0.1:8080/status.json',timeout=2));return dict({k:s.get(k) for k in ['processed','published','capture_sequence_gaps','latest_overwrites','encode_overwrites','processing_ms']},face_count=len(s.get('faces',[])))
try:
    put('tracing_on','0');put('trace_clock','mono');put('buffer_size_kb','4096');put('set_ftrace_filter','\n'.join(functions));put('current_tracer','function')
    put('events/sched/sched_switch/filter',' || '.join(f'prev_pid == {x} || next_pid == {x}' for x in tids))
    put('events/sched/sched_wakeup/filter',' || '.join(f'pid == {x}' for x in tids));put('events/sched/sched_wakeup/enable','1')
    put('events/sched/sched_switch/enable','1');put('trace','');before=status();start=time.monotonic();put('tracing_on','1');samples=[]
    for i in range(20):
        time.sleep(max(0,start+i+1-time.monotonic()));samples.append(status())
    put('tracing_on','0');elapsed=time.monotonic()-start;after=status()
    trace=(t/'trace').read_text();(d/(name+'-trace.txt')).write_text(trace)
    stats={p.name:(p/'stats').read_text() for p in (t/'per_cpu').iterdir() if (p/'stats').exists()}
    (d/(name+'-meta.json')).write_text(json.dumps({'pid':pid,'tids':tids,'elapsed_s':elapsed,'before':before,'after':after,'samples':samples,'stats':stats,'npu_load':Path('/sys/kernel/debug/rknpu/load').read_text(),'npu_freq':Path('/sys/kernel/debug/rknpu/freq').read_text()},indent=2));print('DONE',flush=True)
finally:
    put('tracing_on','0');put('events/sched/sched_switch/enable','0');put('events/sched/sched_wakeup/enable','0');put('current_tracer','nop');t.rmdir()
