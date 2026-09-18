#!/usr/bin/env python3
"""Synthetic concurrent ASR/TTS load: public WAV + fixed text, no live audio/cloud.

Calls only a native ASR subprocess and the existing local Unix speech socket.
Never constructs AudioIO, calls transport.connect(), opens ALSA, or reads cloud keys.
PCM is counted in memory, never played/saved; recognized text is not printed.
"""
import argparse
import audioop
import json
import math
from pathlib import Path
import sys
import threading
import time
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent.parent.parent)
    parser.add_argument("--root", default="/userdata/rtctrl-speech")
    parser.add_argument("--socket", default="/run/rtctrl-companion/speech.sock")
    parser.add_argument("--wav", type=Path, default=Path("/tmp/melo-hybrid-dialogue.wav"))
    args = parser.parse_args()
    sys.path.insert(0, str(args.bundle.resolve()))
    from apps.companion.streaming_asr import StreamingAsr
    from apps.companion.local_voice import LocalVoiceTransport
    from apps.companion.audio import PcmStreamChunk

    # Only a pre-existing, bounded public fixture is read; no audio input is opened.
    with wave.open(str(args.wav), "rb") as source:
        channels, rate, count = source.getnchannels(), source.getframerate(), source.getnframes()
        if source.getsampwidth() != 2 or channels not in (1, 2) or rate not in (8000, 16000, 22050, 24000, 44100, 48000) or not 0 < count <= rate * 20:
            raise ValueError("Expected a public PCM16 WAV of at most 20 seconds")
        pcm = source.readframes(count)
    if channels == 2:
        pcm = audioop.tomono(pcm, 2, .5, .5)
    if rate != 16000:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 16000, None)
    frame_bytes = 1920
    frames = [pcm[i:i + frame_bytes].ljust(frame_bytes, b"\0") for i in range(0, len(pcm), frame_bytes)]
    errors, durations = [], []
    metrics = {"asr_frames": 0, "tts_bytes": 0, "tts_chunks": 0,
               "tts_first_s": None, "tts_total_s": None, "asr_audio_s": len(pcm) / 32000}
    guard = threading.Lock()
    stop = threading.Event()
    start = 0.
    def message(value):
        if isinstance(value, PcmStreamChunk) and value.data:
            with guard:
                if metrics["tts_first_s"] is None:
                    metrics["tts_first_s"] = time.monotonic() - start
                metrics["tts_bytes"] += len(value.data)
                metrics["tts_chunks"] += 1
    def failed(stage, error):
        # Do not expose subprocess text, recognized words, or reply content.
        with guard:
            errors.append(stage + ": " + type(error).__name__)
        stop.set()

    transport = LocalVoiceTransport({"local_speech_root": args.root,
        "local_speech_socket": args.socket, "local_tts_prebuffer_s": 2.,
        "local_tts_timeout_s": 25}, message, lambda _: failed("transport", RuntimeError()))
    transport._closed = False
    asr = None
    threads = []
    try:
        asr = StreamingAsr(args.root)
        start = time.monotonic()
        deadline = start + 30
        def recognize():
            try:
                asr.exchange(3)
                for index, frame in enumerate(frames):
                    # Deliver the first 60ms frame after 60ms, like a real capture source.
                    due = start + (index + 1) * .06
                    if stop.wait(max(0., due - time.monotonic())):
                        return
                    if time.monotonic() >= deadline:
                        raise TimeoutError("probe deadline")
                    before = time.monotonic()
                    asr.exchange(1, frame)
                    with guard:
                        durations.append(time.monotonic() - before)
                        metrics["asr_frames"] += 1
                asr.exchange(2)  # Flush model state, discard recognized text.
            except Exception as error:
                failed("asr", error)
        def synthesize():
            try:
                transport._stream_tts(0, "今天的天气很好，我们一起出去走走吧。")
                with guard:
                    metrics["tts_total_s"] = time.monotonic() - start
            except Exception as error:
                failed("tts", error)
        threads = [threading.Thread(target=recognize, name="probe-asr"),
                   threading.Thread(target=synthesize, name="probe-tts")]
        for thread in threads:
            thread.start()
        while any(thread.is_alive() for thread in threads):
            if stop.wait(.05):
                break
            if time.monotonic() >= deadline:
                failed("deadline", TimeoutError())
                break
    except Exception as error:
        failed("setup", error)
    finally:
        stop.set()
        try:
            transport.close()  # Cancels socket reads; never starts/stops shared worker.
        except Exception as error:
            failed("transport_cleanup", error)
        if asr is not None:
            try:
                asr.close()  # Kills and reaps only this probe's native ASR subprocess.
            except Exception as error:
                failed("asr_cleanup", error)
        for thread in threads:
            thread.join(timeout=6)
            if thread.is_alive():
                failed("thread_cleanup", TimeoutError())
        if asr is not None and all(not t.is_alive() for t in threads):
            for pipe in (asr.process.stdin, asr.process.stdout):
                if pipe:
                    pipe.close()
    ordered = sorted(durations)
    metrics["asr_exchange_max_ms"] = max(ordered) * 1000 if ordered else None
    metrics["asr_exchange_p95_ms"] = ordered[max(0, math.ceil(.95 * len(ordered)) - 1)] * 1000 if ordered else None
    metrics["errors"] = errors
    metrics["scope"] = "public fixture, local Unix TTS, counted PCM only; no mic/playback/cloud"
    print(json.dumps(metrics, ensure_ascii=False), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
