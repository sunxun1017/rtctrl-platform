"""Bounded, isolated sched tracing. No mounts or global tracing writes.
Usage: capture=SchedCapture(); status=capture.start(tids)
try: benchmark()
finally: summary=capture.finish(outputdir)
Call finish even after benchmark failure. Capture window must be bounded by caller.
"""
from itertools import islice
import json
import os
from pathlib import Path
import re
import time

LINE = re.compile(r"\[(\d+)\].*?\s(\d+\.\d+):\s+(sched_switch|sched_wakeup):\s+(.*)")
SWITCH = re.compile(r"prev_pid=(\d+).*?prev_state=(\S+).*?next_pid=(\d+)")
WAKE = re.compile(r"\bpid=(\d+)")


def parse_trace(text, tids):
    """Observed intervals only; omit unknown leading and trailing intervals."""
    wanted = set(tids)
    info = {tid: dict(running_s=0.0, runnable_s=0.0, sleeping_s=0.0,
                     switches_in=0, wakeups=0) for tid in wanted}
    states = {}
    first = last = None
    events = 0
    def transition(tid, state, ts):
        if tid not in wanted:
            return
        old = states.get(tid)
        if old and ts >= old[1]:
            info[tid][old[0] + '_s'] += ts - old[1]
        states[tid] = state, ts
    for line in text.splitlines():
        match = LINE.search(line)
        if not match:
            continue
        ts, event, body = float(match[2]), match[3], match[4]
        first = ts if first is None else min(first, ts)
        last = ts if last is None else max(last, ts)
        events += 1
        if event == 'sched_switch':
            detail = SWITCH.search(body)
            if not detail:
                continue
            prev, state, nxt = int(detail[1]), detail[2], int(detail[3])
            transition(prev, 'runnable' if state.startswith('R') else 'sleeping', ts)
            transition(nxt, 'running', ts)
            if nxt in wanted:
                info[nxt]['switches_in'] += 1
        else:
            detail = WAKE.search(body)
            if detail and int(detail[1]) in wanted:
                tid = int(detail[1])
                info[tid]['wakeups'] += 1
                # Duplicate wakeups must not restart existing runnable accounting.
                if tid not in states or states[tid][0] == 'sleeping':
                    transition(tid, 'runnable', ts)
    for row in info.values():
        row['offcpu_s'] = row['runnable_s'] + row['sleeping_s']
    return dict(observed_events=events, first_timestamp=first, last_timestamp=last,
                intervals='between observed transitions; leading/trailing partial intervals omitted',
                tids={str(k): v for k, v in sorted(info.items())})


class SchedCapture:
    def __init__(self, buffer_kb=256):
        if type(buffer_kb) is not int or buffer_kb not in (256, 512, 2048):
            raise ValueError('buffer_kb must be 256, 512 or 2048 per CPU')
        self.buffer_kb = buffer_kb
        self.instance = None
        self.tids = []
        self.reason = None
        self.started = None

    def _write(self, relative, value):
        (self.instance / relative).write_text(str(value))

    def start(self, tids):
        if self.instance is not None:
            raise RuntimeError('capture already started')
        tids = list(islice(iter(tids), 129))
        if not tids or len(tids) > 128 or any(type(t) is not int or t <= 0 for t in tids):
            raise ValueError('expected 1..128 positive integer TIDs')
        tids = sorted(set(tids))
        self.tids = tids
        self.reason = None
        roots = [Path('/sys/kernel/tracing'), Path('/sys/kernel/debug/tracing')]
        root = next((r for r in roots if (r / 'instances').is_dir()), None)
        if root is None:
            self.reason = 'tracefs instances unavailable; no mount attempted'
            return {'available': False, 'reason': self.reason}
        path = root / 'instances' / ('rtctrl-melo-' + str(os.getpid()))
        try:
            # Refuse an existing instance; never overwrite unrelated tracing.
            path.mkdir()
            self.instance = path
            self._write('tracing_on', '0')
            self._write('buffer_size_kb', self.buffer_kb)
            self._write('trace_clock', 'mono')
            self._write('events/sched/sched_switch/filter', ' || '.join(
                '(prev_pid == %d || next_pid == %d)' % (t, t) for t in tids))
            self._write('events/sched/sched_wakeup/filter', ' || '.join(
                '(pid == %d)' % t for t in tids))
            self._write('events/sched/sched_switch/enable', '1')
            self._write('events/sched/sched_wakeup/enable', '1')
            self._write('trace', '')
            self.started = time.monotonic()
            self._write('tracing_on', '1')
            return {'available': True, 'instance': str(path), 'tids': tids,
                    'buffer_kb_per_cpu': self.buffer_kb}
        except OSError as exc:
            self.reason = 'sched trace unavailable: ' + str(exc)
            cleanup_errors = self._cleanup()
            return {'available': False, 'reason': self.reason, 'cleanup_errors': cleanup_errors}

    def _cleanup(self):
        errors = []
        if self.instance is not None:
            for file in ('tracing_on', 'events/sched/sched_switch/enable',
                         'events/sched/sched_wakeup/enable'):
                try:
                    self._write(file, '0')
                except OSError as exc:
                    errors.append(str(exc))
            try:
                self.instance.rmdir()
            except OSError as exc:
                errors.append(str(exc))
            self.instance = None
        return errors

    def finish(self, outputdir):
        result = {'available': self.instance is not None, 'reason': self.reason}
        try:
            out = Path(outputdir)
            out.mkdir(parents=True, exist_ok=True)
            if self.instance is not None:
                self._write('tracing_on', '0')
                result['elapsed_s'] = time.monotonic() - self.started
                text = (self.instance / 'trace').read_text()
                (out / 'sched-trace.txt').write_text(text)
                stats = {}
                lost = False
                for file in sorted((self.instance / 'per_cpu').glob('cpu*/stats')):
                    content = file.read_text()
                    stats[file.parent.name] = content
                    for label, value in re.findall(r'^([^:\n]+):\s*(\d+)', content, re.M):
                        if ('overrun' in label or 'dropped' in label) and int(value):
                            lost = True
                if re.search(r'LOST\s+\d+\s+EVENTS', text):
                    lost = True
                (out / 'sched-percpu-stats.json').write_text(json.dumps(stats, indent=2))
                result.update(parse_trace(text, self.tids))
                result['lost_events'] = lost
                result['reliable_intervals'] = bool(stats) and not lost
                result['buffer_kb_per_cpu'] = self.buffer_kb
        except OSError as exc:
            result['error'] = str(exc)
        finally:
            result['cleanup_errors'] = self._cleanup()
        try:
            (Path(outputdir) / 'sched-summary.json').write_text(json.dumps(result, indent=2))
        except OSError as exc:
            result['summary_write_error'] = str(exc)
        return result
