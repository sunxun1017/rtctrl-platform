#!/usr/bin/env python3
"""Run both standalone preview modes on the board; exclusive camera access required."""
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request


def cpu_seconds(pids):
    total = 0
    for pid in pids:
        fields = Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()
        total += int(fields[11]) + int(fields[12])
    return total / os.sysconf("SC_CLK_TCK")


def rss_kb(pids):
    return sum(int(re.search(r"VmRSS:\s+(\d+)",
                            Path("/proc/%d/status" % pid).read_text()).group(1))
               for pid in pids)


def latency_summary(trace):
    values = []
    for line in trace.read_text().splitlines():
        if " latency," in line and "sink-element=(string)fdsink" in line:
            match = re.search(r"time=\(guint64\)(\d+).*ts=\(guint64\)(\d+)", line)
            if match and int(match[2]) > 3_000_000_000:
                values.append(int(match[1]) / 1e6)
    if not values:
        return {}
    return dict(pipeline_latency_mean_ms=statistics.mean(values),
                pipeline_latency_p95_ms=sorted(values)[int(0.95 * (len(values) - 1))],
                pipeline_latency_samples=len(values))


def run(mode, seconds, directory):
    trace = directory / (mode + "-trace.log")
    env = dict(os.environ, GST_TRACERS="latency(flags=pipeline)",
               GST_DEBUG="GST_TRACER:7", GST_DEBUG_NO_COLOR="1", GST_DEBUG_FILE=str(trace))
    with (directory / (mode + "-server.log")).open("w") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("preview.py")),
                                    "--mode", mode, "--port", "8081", "--log",
                                    str(directory / (mode + "-pipeline.log"))],
                                   stdout=log, stderr=log, env=env)
    def status():
        with urllib.request.urlopen("http://127.0.0.1:8081/status.json", timeout=2) as response:
            return json.load(response)
    stream = None
    try:
        deadline = time.monotonic() + 8
        while True:
            if process.poll() is not None:
                raise RuntimeError("Preview exited; inspect benchmark logs")
            try:
                if status()["frames"] > 60:
                    break
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Preview startup timeout")
            time.sleep(0.2)
        stream = urllib.request.urlopen("http://127.0.0.1:8081/stream.mjpg", timeout=2)
        def consume():
            try:
                while stream.read(65536):
                    pass
            except (OSError, ValueError):
                pass
        consumer = threading.Thread(target=consume, daemon=True)
        consumer.start()
        # CONFIG_CHECKPOINT_RESTORE may be off: /proc/.../children is optional.
        pids = [process.pid]
        for stat in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = stat.read_text().rsplit(")", 1)[1].split()
                if int(fields[1]) == process.pid:
                    pids.append(int(stat.parent.name))
            except (OSError, ValueError):
                pass
        begin_frames, begin_cpu, begin = status()["frames"], cpu_seconds(pids), time.monotonic()
        samples = []
        for _ in range(seconds):
            time.sleep(1)
            sample = status()
            if not sample["running"] or sample["error"]:
                raise RuntimeError(str(sample))
            samples.append(sample)
        elapsed = time.monotonic() - begin
        result = dict(mode=mode, seconds=elapsed, samples=len(samples),
                      fps=(samples[-1]["frames"] - begin_frames) / elapsed,
                      cpu_percent_one_core=100 * (cpu_seconds(pids) - begin_cpu) / elapsed,
                      combined_rss_kb=rss_kb(pids),
                      mean_jpeg_bytes=statistics.mean(s["jpeg_bytes"] for s in samples))
    finally:
        process.terminate()
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if stream:
            stream.close()
    result.update(latency_summary(trace))
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--output", default="benchmark")
    parser.add_argument("--analyze-only", action="store_true", help="Re-read saved traces/results")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 300:
        parser.error("seconds must be 5..300")
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.analyze_only:
        results = json.loads((directory / "results.json").read_text())
        for result in results:
            result.update(latency_summary(directory / (result["mode"] + "-trace.log")))
        print(json.dumps(results, indent=2))
    else:
        results = [run(mode, args.seconds, directory) for mode in ("software", "hardware")]
    (directory / "results.json").write_text(json.dumps(results, indent=2) + "\n")
