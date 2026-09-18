#!/usr/bin/env python3
"""Isolated bounded Melo benchmark using fixed public text, no mic/cloud/playback.
Stop the interactive speech service first. Requires its matching installed models.
Controller attaches perf to a dedicated benchmark child; perf finishes after child exit.
Run perf report separately afterward. ftrace observes startup TIDs only.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import select
import signal
import subprocess
import sys
import time


def child_main(args):
    sys.path[:0] = [str(args.root / "python"), str(Path(__file__).resolve().parents[2])]
    import sherpa_onnx
    from apps.companion.melo_npu import MeloNpu
    from ftrace_sched import SchedCapture
    start = time.monotonic()
    engine = MeloNpu(args.root, sherpa_onnx, args.threads)
    texts = [("short", "今天的天气很好，我们一起出去走走吧。"),
             ("dialogue", "你今天过得怎么样？如果有点累，我们就先休息一会儿。等你准备好了，再慢慢跟我说，我会认真听的。")]
    metadata = {"load_s": time.monotonic() - start, "threads": args.threads,
                "bucket": engine.decoder.frames, "kernel": os.uname().release,
                "sherpa": sherpa_onnx.__version__}
    engine.synthesize(texts[0][1])  # Exclude warmup from measured rounds.
    rows = []
    trace = SchedCapture(2048) if args.ftrace else None
    print(json.dumps({"ready": True, "pid": os.getpid()}), flush=True)
    if sys.stdin.readline().strip() != "start":
        raise RuntimeError("controller did not authorize benchmark start")
    try:
        if trace:
            metadata["trace"] = trace.start([int(p.name) for p in Path("/proc/self/task").iterdir()])
        for index in range(args.rounds):
            for name, text in texts:
                start, cpu = time.monotonic(), time.process_time()
                samples, rate = engine.synthesize(text)
                row = {"round": index, "text_case": name, "wall_s": time.monotonic() - start,
                       "cpu_s": time.process_time() - cpu, "audio_s": len(samples) / rate,
                       "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
                rows.append(row)
                print(json.dumps(row), flush=True)
    finally:
        # Close trace window before potentially slow perf cleanup.
        if trace:
            metadata["trace_result"] = trace.finish(args.output)
        (args.output / "results.json").write_text(json.dumps(
            {"metadata": metadata, "measurements": rows}, indent=2))
    return 0


def stop_process(process, warnings, name, natural_timeout=0):
    """Reap only the direct child we created, with bounded escalation."""
    try:
        process.wait(timeout=natural_timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    warnings.append(name + " did not exit naturally; sent SIGINT")
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        warnings.append(name + " required forced termination; validate artifacts")
        process.kill()
        process.wait(timeout=5)


def wait_ready(process, timeout=120):
    deadline = time.monotonic() + timeout
    # Read bytes directly: TextIO buffering can hide a buffered ready line from select.
    pending = bytearray()
    while time.monotonic() < deadline:
        readable, _, _ = select.select([process.stdout], [], [], min(1, max(0, deadline-time.monotonic())))
        if not readable:
            if process.poll() is not None:
                raise RuntimeError("benchmark child exited before readiness")
            continue
        block = os.read(process.stdout.fileno(), 4096)
        if not block:
            raise RuntimeError("benchmark child closed readiness pipe")
        pending.extend(block)
        if len(pending) > 1024 * 1024:
            raise RuntimeError("excessive child startup output")
        while b"\n" in pending:
            line, _, remainder = pending.partition(b"\n")
            pending = bytearray(remainder)
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(value, dict) and value.get("ready") is True and value.get("pid") == process.pid:
                return
    raise TimeoutError("benchmark child readiness exceeded 120 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, choices=(1, 2), default=2)
    parser.add_argument("--rounds", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--perf", action="store_true")
    parser.add_argument("--ftrace", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child_main(args)
    for directory in Path("/proc").iterdir():
        if directory.name.isdecimal() and int(directory.name) != os.getpid():
            try:
                argv = (directory / "cmdline").read_bytes().split(b"\0")
                if b"apps.companion.speech_worker" in argv:
                    parser.error("Stop the interactive speech worker before isolated profiling")
            except (FileNotFoundError, PermissionError):
                pass
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(Path(__file__).resolve()), "--child", "--root", str(args.root),
               "--output", str(args.output), "--threads", str(args.threads), "--rounds", str(args.rounds)]
    if args.ftrace:
        command.append("--ftrace")
    child = None
    processes, handles, warnings = [], [], []
    code = 1
    def interrupted(signum, frame):
        raise RuntimeError("controller interrupted by signal " + str(signum))
    previous_term = signal.signal(signal.SIGTERM, interrupted)
    try:
        stderr = (args.output / "benchmark-stderr.log").open("w")
        handles.append(stderr)
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
        wait_ready(child)
        if args.perf:
            commands = [
                ["perf", "stat", "-p", str(child.pid), "-e",
                 "task-clock,context-switches,cpu-migrations,page-faults,cycles,instructions,cache-misses",
                 "-o", str(args.output / "perf-stat.txt")],
                ["perf", "record", "-p", str(child.pid), "-e", "cycles", "-F", "49",
                 "-o", str(args.output / "perf.data")]]
            for i, perf_command in enumerate(commands):
                handle = (args.output / ("perf-%d.log" % i)).open("w")
                handles.append(handle)
                processes.append(subprocess.Popen(perf_command, stdout=subprocess.DEVNULL, stderr=handle))
            # Allow perf to attach before releasing the benchmark; fail early if unavailable.
            time.sleep(.25)
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("perf exited before benchmark start; inspect perf logs")
        child.stdin.write(b"start\n")
        child.stdin.flush()
        output, _ = child.communicate(timeout=180 * args.rounds + 30)
        (args.output / "benchmark-stdout.log").write_bytes(output)
        code = child.returncode
        if code:
            warnings.append("benchmark child failed with exit code " + str(code))
    except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
        warnings.append(str(error))
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        if child is not None:
            stop_process(child, warnings, "benchmark child")
            if child.stdin:
                child.stdin.close()
            if child.stdout:
                child.stdout.close()
        # The observed process has now exited, so perf can finish naturally.
        for process in processes:
            stop_process(process, warnings, "perf", natural_timeout=5)
            if process.returncode:
                warnings.append("perf exit code " + str(process.returncode))
        for handle in handles:
            handle.close()
        (args.output / "controller.json").write_text(json.dumps({"exit_code": code, "warnings": warnings}, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
