"""Explicit ten-second local acoustic test. Never saves/uploads captured PCM."""
import argparse
import audioop
import json
import math
import resource
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.companion.audio import AudioIO, PcmAudio
from apps.companion.aec import EchoCanceller


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-local-acoustic-test", action="store_true", required=True)
    parser.add_argument("--wav", required=True, help="Fixed test speech, never user recording")
    parser.add_argument("--library", required=True)
    parser.add_argument("--capture-device", default="rtctrl_es8389_capture")
    parser.add_argument("--playback-device", default="rtctrl_es8389")
    args = parser.parse_args()
    with wave.open(args.wav, "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Fixed fixture must be mono PCM16")
        rate = source.getframerate()
        pcm = source.readframes(min(source.getnframes(), int(rate * 8)))
    config = dict(aec_enabled=True, aec_library=args.library,
                  capture_device=args.capture_device, playback_device=args.playback_device)
    errors = []
    io = AudioIO(config, errors.append)
    first = io._aec
    second = EchoCanceller(dict(config, aec_enable_aes=True))

    class Comparison:
        def render(self, *values):
            first.render(*values)
            second.render(*values)
        def process(self, *values):
            result = first.process(*values)
            second.process(*values)
            return result
        def reset_reference(self):
            first.reset_reference()
            second.reset_reference()
        def close(self):
            first.close()
            second.close()

    io._aec = Comparison()
    before_cpu = time.process_time()
    started = time.monotonic()
    snapshots = []
    try:
        io.start(lambda clean: None)
        time.sleep(.5)
        io.play_pcm(PcmAudio(pcm, rate))
        while time.monotonic() - started < 10:
            if errors:
                raise RuntimeError(errors[-1])
            snapshots.append((round(time.monotonic() - started, 3), first.snapshot(), second.snapshot()))
            time.sleep(.1)
    finally:
        io.stop()
    elapsed = time.monotonic() - started
    # Exclude startup and playback tail; energy ratio is not speech intelligibility.
    lo = next(x for x in snapshots if x[0] >= 3)
    hi = next(x for x in snapshots if x[0] >= 7.5)
    modes = []
    for index in (1, 2):
        delta = {k: hi[index][k] - lo[index][k] for k in hi[index]}
        mic, out = delta["mic_energy"], delta["output_energy"]
        delta["echo_only_energy_reduction_db"] = round(10 * math.log10(mic / max(1, out)), 2) if mic else None
        modes.append(delta)
    print(json.dumps(dict(duration_s=round(elapsed, 3), cpu_seconds=round(time.process_time()-before_cpu, 3),
                          peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                          measurement_window_s=[lo[0], hi[0]], modes=modes, errors=errors)))


if __name__ == "__main__":
    main()
