# CORRECTION: raw model probes are not app output

All WAV candidates in this directory and the earlier raw ORT sentence fixtures bypassed sherpa-onnx `GeneratedAudio::ScaleSilence`, whose normal config defaults to 0.2. They must not be described as the full current application waveform. The token/duration findings below remain valid but raw-sample subjective rejection cannot by itself judge actual sherpa output. CPU/NPU decoder agreement is decoder-level evidence only.

ScaleSilence treats contiguous abs(sample)<=0.01 runs of at least 0.2s as pauses; trailing run uses strictly >0.2s. It retains only the first trunc(float32(length)*scale) samples of each qualifying pause. It does not change voiced speech speed. Apply after full floating-point decoder output, before PCM conversion and once per same Process batch, not per NPU chunk. Native C++ implementation extracted from pinned v1.13.8 is scale_silence_reference.cc; float32-compatible Python is scale_silence.py.

# AISHELL3 sid0 rhythm audit 2026-09-18

Read-only production audit; all experiments remain in work/tts-prosody.

## Findings

- Frozen actual sherpa-onnx frontend fixture is one sentence/one callback batch, not one audio inference per Chinese character.
- Official lexicon contains #0 after each syllable. sherpa v1.13.8 Lexicon calls it `pad`; upstream AISHELL3 frontend explicitly emits `[initial, final+tone, #0]` for every syllable. Removing #0 violates that convention.
- Actual graph duration output `/Ceil_output_0` shows #0 has nonzero durations, but aligned decoder waveform segments are voiced: mostly RMS 0.03–0.08 and peaks over 0.1. These are not empty gaps that can safely be cut out. Frame hop = 256/8000 = 32 ms.
- The model metadata has no punctuations field. sherpa Lexicon therefore ignores the comma in the example; the upstream Chinese frontend emits sil at each comma clause boundary. This is a verified frontend difference, but does not prove the cause of character-by-character articulation.
- Current single-character dictionary/fst route has no contextual tone sandhi/prosody predictor. Actual tokens keep 一起 as i1/qi3 and 很好 as hen3/hao3. This limits phrasing; replacement frontend/model should handle context.

## Samples

Text: 今天的天气很好，我们一起出去走走吧
All samples original sid0 8kHz, no loudness normalization, no deleted tokens, no postprocessing. Duration noise is stochastic; regenerated samples need not match waveform exactly.

- sid0-noise-0.8-speed-1.0.wav: default, 5.888 s.
- sid0-noise-0.35-speed-1.15.wav: reduced duration noise + modest acceleration, 5.248 s. Faster is not evidence of more natural speech.
- sid0-noise-0-speed-1.0.wav: deterministic duration predictor, 5.568 s.
- sid0-comma-sil-noise-0.35-speed-1.15.wav: same candidate settings, only adds sil at comma boundary following upstream frontend. Experimental, no production change.

`durations.py` / `comma.py` regenerate probes; `durations.json` / `comma-durations.json` preserve actual per-token duration and voiced segment measurements.

## Primary sources

- https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/sherpa-onnx/csrc/lexicon.cc
- https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/sherpa-onnx/csrc/offline-tts-vits-impl.h
- https://github.com/csukuangfj/vits_chinese/blob/master/test_aishell3.py (get_phoneme4pinyin; chinese_to_phonemes)
- https://github.com/csukuangfj/vits_chinese/blob/master/generate_lexicon_aishell3.py

No subjective naturalness acceptance claimed.
