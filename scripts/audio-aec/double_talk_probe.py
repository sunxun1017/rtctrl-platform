"""User-coordinated double-talk probe; PCM/transcripts stay in RAM, never uploaded."""
import argparse
import audioop
import json
import sys
import time
import wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.companion.audio import AudioIO, PcmAudio
from apps.companion.aec import EchoCanceller
from apps.companion.streaming_asr import StreamingAsr

TARGET = "今天天气不错我想出去散步"


def phrase_score(text):
    # Minimum edit distance to any substring, tolerating unrelated playback speech.
    text = "".join(c for c in text if c.isalnum())
    previous = [0] * (len(text) + 1)
    for i, wanted in enumerate(TARGET, 1):
        current = [i]
        for j, got in enumerate(text, 1):
            current.append(min(previous[j] + 1, current[j-1] + 1,
                               previous[j-1] + (wanted != got)))
        previous = current
    return {"target_best_edit_distance": min(previous),
            "target_characters": len(TARGET), "exact_repetitions": text.count(TARGET),
            "recognized_characters": len(text)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-local-double-talk-test", action="store_true", required=True)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--library", required=True)
    ap.add_argument("--speech-root", required=True)
    args = ap.parse_args()
    with wave.open(args.wav) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("Fixture must be mono PCM16")
        rate = w.getframerate()
        fixture = w.readframes(min(w.getnframes(), rate * 8)) * 2
    if len(fixture) / (rate * 2) < 15:
        raise ValueError("Fixture must cover the entire overlap scoring window")
    # Reject a fixture containing the target before opening the microphone.
    fixture_pcm, _ = audioop.ratecv(fixture[:len(fixture)//2], 2, 1, rate, 16000, None)
    check = StreamingAsr(args.speech_root)
    try:
        check.exchange(3)
        for pos in range(0, len(fixture_pcm), 1920):
            check.exchange(1, fixture_pcm[pos:pos+1920])
        fixture_score = phrase_score(check.exchange(2).get("text", ""))
        if fixture_score["target_best_edit_distance"] < 6:
            raise ValueError("Fixture may contain target; choose different test speech")
    finally:
        check.close()
    print("FIXTURE_CHECK_PASSED_CAPTURE_START", flush=True)
    errors = []
    config = dict(aec_enabled=True, aec_library=args.library,
                  capture_device="rtctrl_es8389_capture", playback_device="rtctrl_es8389")
    io = AudioIO(config, errors.append)
    pure, aes = io._aec, EchoCanceller(dict(config, aec_enable_aes=True))
    signals = [bytearray(), bytearray(), bytearray()]

    class Comparison:
        def render(self, *a):
            pure.render(*a); aes.render(*a)
        def process(self, pcm, stamp):
            clean, suppressed = pure.process(pcm, stamp), aes.process(pcm, stamp)
            if len(signals[0]) + len(pcm) > 16000 * 2 * 21:
                raise RuntimeError("Bounded test exceeded")
            # Strictly inside sustained playback; exclude startup and tail.
            elapsed = stamp - io.first_write_monotonic
            if io.first_write_monotonic and 2 <= elapsed <= 14:
                for dest, source in zip(signals, (pcm, clean, suppressed)):
                    dest.extend(source)
            return clean
        def reset_reference(self):
            pure.reset_reference(); aes.reset_reference()
        def close(self):
            pure.close(); aes.close()

    io._aec = Comparison()
    started = time.monotonic()
    try:
        io.start(lambda clean: None)
        time.sleep(.5)
        io.play_pcm(PcmAudio(fixture, rate))
        while time.monotonic() - started < 17:
            if errors:
                raise RuntimeError(errors[-1])
            time.sleep(.05)
    finally:
        io.stop()
    print("CAPTURE_CLOSED_LOCAL_ASR_START", flush=True)
    recognizer = None
    try:
        recognizer = StreamingAsr(args.speech_root)
        results = []
        for name, data in zip(("raw", "aec", "aec_aes"), signals):
            recognizer.exchange(3)
            for start in range(0, len(data), 1920):
                recognizer.exchange(1, bytes(data[start:start+1920]))
            text = recognizer.exchange(2).get("text", "")
            results.append(dict(mode=name, **phrase_score(text),
                                rms=audioop.rms(data, 2), peak=audioop.max(data, 2)))
        print(json.dumps(dict(scored_window_after_first_write_s=[2,14], scored_samples=len(signals[0])//2, fixture_target_distance=fixture_score["target_best_edit_distance"], results=results, pure=pure.snapshot(), aes=aes.snapshot(), errors=errors)), flush=True)
    finally:
        if recognizer:
            recognizer.close()
        for data in signals:
            data[:] = b"\x00" * len(data)
            data.clear()


if __name__ == "__main__":
    main()
