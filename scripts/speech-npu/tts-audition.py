#!/usr/bin/env python3
"""Generate a local TTS listening candidate without changing a running service."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("aishell3", "melo", "kokoro"))
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("text")
    parser.add_argument("--speaker", type=int, default=0)
    parser.add_argument("--speed", type=float, default=1)
    parser.add_argument("--duration-noise", type=float, default=.8)
    args = parser.parse_args()
    if not .5 <= args.speed <= 2 or not 0 <= args.duration_noise <= 1:
        parser.error("speed must be .5..2 and duration-noise must be 0..1")
    if args.output.exists():
        parser.error("output already exists")
    import sherpa_onnx as s
    root = args.model_dir.resolve()
    if args.kind == "kokoro":
        model = root / "model.int8.onnx"
        if not model.exists():
            model = root / "model.onnx"
        config = s.OfflineTtsModelConfig(kokoro=s.OfflineTtsKokoroModelConfig(
            model=str(model), voices=str(root / "voices.bin"), tokens=str(root / "tokens.txt"),
            lexicon=str(root / "lexicon-zh.txt"), data_dir=str(root / "espeak-ng-data"),
            dict_dir=str(root / "dict"), lang="zh"), num_threads=2)
        rules = ["date-zh.fst", "number-zh.fst", "phone-zh.fst"]
    else:
        model = root / "model.onnx"
        vits = s.OfflineTtsVitsModelConfig(model=str(model), tokens=str(root / "tokens.txt"),
            lexicon=str(root / "lexicon.txt"), noise_scale_w=args.duration_noise)
        if args.kind == "melo":
            vits.dict_dir = str(root / "dict")
        config = s.OfflineTtsModelConfig(vits=vits, num_threads=2)
        rules = ["date.fst", "number.fst", "phone.fst"]
        if args.kind == "aishell3":
            rules.append("new_heteronym.fst")
    start = time.monotonic()
    tts = s.OfflineTts(s.OfflineTtsConfig(model=config,
        rule_fsts=",".join(str(root / item) for item in rules)))
    load_seconds = time.monotonic() - start
    start = time.monotonic()
    result = tts.generate(args.text, sid=args.speaker, speed=args.speed)
    generation_seconds = time.monotonic() - start
    args.output.parent.mkdir(parents=True, exist_ok=True)
    s.write_wave(str(args.output), result.samples, result.sample_rate)
    report = {"kind": args.kind, "text": args.text, "speaker": args.speaker,
        "speed": args.speed, "duration_noise": args.duration_noise if args.kind != "kokoro" else None,
        "sample_rate": result.sample_rate, "audio_seconds": len(result.samples) / result.sample_rate,
        "load_seconds": load_seconds, "generation_seconds": generation_seconds,
        "machine": platform.machine(), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "sherpa_version": s.__version__, "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "subjective_naturalness": "not_evaluated"}
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
