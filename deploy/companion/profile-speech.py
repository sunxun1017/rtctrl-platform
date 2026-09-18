#!/usr/bin/env python3
"""Bounded local benchmark; no microphone, playback, network or transcript logging.

Use a public 16kHz mono PCM16 WAV. Run only while interactive voice is idle.
Optionally wrap this command with perf stat -p WORKER_PID -- python3 profile-speech.py ... .
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import tempfile
import time
import wave


def request(path, value, expected_pid):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(120)
        peer.connect(path)
        actual_pid, _, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        if actual_pid != expected_pid:
            raise RuntimeError("Socket peer does not match worker PID")
        peer.sendall(json.dumps(value).encode() + b"\n")
        data = bytearray()
        while b"\n" not in data:
            block = peer.recv(4096 - len(data))
            if not block or len(data) + len(block) >= 4096:
                raise RuntimeError("Invalid worker response")
            data.extend(block)
        result = json.loads(data)
        if not result.get("ok"):
            raise RuntimeError("Worker unavailable or busy")
        return result


def resources(pid):
    base = Path("/proc") / str(pid)
    fields = (base / "stat").read_text().rsplit(")", 1)[1].split()
    result = {"ticks": int(fields[11]) + int(fields[12]), "start_ticks": int(fields[19])}
    for line in (base / "status").read_text().splitlines():
        if line.startswith(("VmRSS:", "VmHWM:", "Threads:")):
            result[line.split(":")[0]] = int(line.split()[1])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--rounds", type=int, choices=range(1, 21), default=4)
    args = parser.parse_args()
    if args.pid <= 0 or args.wav.stat().st_size > 2 * 1024 * 1024:
        parser.error("Expected positive worker PID and WAV <=2MiB")
    with wave.open(str(args.wav), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000) or source.getnframes() > 16000 * 60:
            parser.error("Expected <=60s mono PCM16 16kHz WAV")
    health = request(args.socket, {"operation": "health"}, args.pid)
    if not health.get("ready") or health.get("busy"):
        parser.error("Worker not ready or busy; wait for the current turn")
    print(json.dumps({"input_sha256": hashlib.sha256(args.wav.read_bytes()).hexdigest(), "pid": args.pid}), flush=True)
    with tempfile.TemporaryDirectory(prefix="rtctrl-voice-") as directory:
        source = str(Path(directory) / "input.wav")
        shutil.copyfile(args.wav, source)
        for index in range(args.rounds):
            for operation in ("asr", "tts"):
                before = resources(args.pid)
                started = time.monotonic()
                request(args.socket, {"operation": operation, "input": source,
                        "output": str(Path(directory) / ("out.json" if operation == "asr" else "out.wav")),
                        "text": "你好呀，我是小伴。今天有什么想和我聊的吗？"}, args.pid)
                elapsed = time.monotonic() - started
                audio_s = None
                if operation == "tts":
                    with wave.open(str(Path(directory) / "out.wav"), "rb") as output:
                        audio_s = output.getnframes() / output.getframerate()
                after = resources(args.pid)
                if before["start_ticks"] != after["start_ticks"]:
                    raise RuntimeError("Worker was replaced during profiling")
                print(json.dumps({"round": index, "operation": operation,
                    "wall_s": round(elapsed, 4), "audio_s": audio_s,
                    "rtf": round(elapsed / audio_s, 4) if audio_s else None,
                    "cpu_s": (after["ticks"] - before["ticks"]) / os.sysconf("SC_CLK_TCK"),
                    "rss_kib": after.get("VmRSS"), "peak_rss_kib": after.get("VmHWM"),
                    "threads": after.get("Threads")}), flush=True)


if __name__ == "__main__":
    main()
