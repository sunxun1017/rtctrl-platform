import re,json,collections,statistics,sys
from pathlib import Path
name=sys.argv[1] if len(sys.argv)>1 else 'baseline'
meta=json.loads(Path('work/ftrace-'+name+'-meta.json').read_text());tids=set(meta['tids']);functions=collections.Counter();jobs=[];pending=None;overlaps=0;running={};cpu=collections.defaultdict(list);waits=collections.defaultdict(list);off={};wake={};latency=collections.defaultdict(list)
for line in Path('work/ftrace-'+name+'.txt').read_text().splitlines():
    m=re.search(r'-(\d+)\s+\[(\d+)\]\s+\S+\s+(\d+\.\d+): (.*)',line)
    if not m:continue
    pid,core=int(m[1]),int(m[2]);t=float(m[3]);event=m[4]
    if event.startswith('sched_wakeup:'):
        q=re.search(r'pid=(\d+)',event)
        if q and int(q[1]) in tids:wake.setdefault(int(q[1]),t)
    elif event.startswith('sched_switch:'):
        q=re.search(r'prev_pid=(\d+).*prev_state=(\S+) ==>.*next_pid=(\d+)',event)
        if not q:continue
        prev,nxt=int(q[1]),int(q[3])
        if prev in tids:
            if prev in running:cpu[prev].append((t-running.pop(prev))*1000)
            off[prev]=(t,q[2])
        if nxt in tids:
            if nxt in wake:latency[nxt].append((t-wake.pop(nxt))*1000)
            if nxt in off:
                start,state=off.pop(nxt);waits[(nxt,state)].append((t-start)*1000)
            running[nxt]=t
    else:
        fn=event.split()[0];functions[fn]+=1
        if fn=='rknpu_job_schedule':
            if pending is not None:overlaps+=1
            pending=t
        elif fn=='rknpu_core0_irq_handler' and pending is not None:
            jobs.append((t-pending)*1000);pending=None
def stat(a):
    return {'count':len(a),'sum_ms':sum(a),'mean_ms':statistics.mean(a),'min_ms':min(a),'max_ms':max(a),'p95_ms':sorted(a)[int((len(a)-1)*.95)]} if a else None
result={'elapsed_s':meta['elapsed_s'],'frames':meta['after']['processed']-meta['before']['processed'],'functions':dict(functions),'job_schedule_to_irq':stat(jobs),'overlapping_schedules':overlaps,'job_durations_below_4ms':stat([x for x in jobs if x<4]),'job_durations_at_least_4ms':stat([x for x in jobs if x>=4]),'thread_cpu':{str(k):stat(v) for k,v in cpu.items()},'thread_offcpu':{str(k):stat(v) for k,v in waits.items()},'wakeup_to_run':{str(k):stat(v) for k,v in latency.items()},'scope':'schedule entry to core0 IRQ entry is a driver proxy, not exact NPU MAC active time; no job IDs; only pair if no overlap'}
Path('work/ftrace-'+name+'-analysis.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
