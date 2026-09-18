# Experimental RV1126B software-reference AEC

This bridge references the user-supplied ALIENTEK BSP headers/libraries; it does not
vendor the SDK, install system libraries, open ALSA, record audio, or contact a service.
The ordinary CPU VQE library is used, not the AINR/RKNN variant.

## Build

```bash
SDK=/absolute/path/to/atk_dlrv1126b_linux6.1_sdk
CXX="$SDK/prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-g++"
cmake -S scripts/audio-aec -B work/audio-aec/build \
  -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DCMAKE_CXX_COMPILER="$CXX" -DCMAKE_BUILD_TYPE=Release \
  -DRKAUDIO_ROOT="$SDK/external/common_algorithm/audio/rkaudio_algorithms"
cmake --build work/audio-aec/build -j2
```

Artifacts are `librtctrl_aec.so` and `aec_probe`. Place the BSP's ordinary
`lib64/librkaudio_vqe.so` and `lib64/librkaudio_common.so` beside them in a private
application directory. The bridge uses `$ORIGIN` library search path. System libc/libm/libdl and
libstdc++ are also required. Do not overwrite system VQE/RKNN libraries.

## Contract

`aec_bridge.h` documents the serialized single-owner C ABI. Each process call requires
256 microphone and 256 playback-reference samples, mono PCM16 at 16kHz (16ms).
The bridge interleaves mic/ref, calls the vendor API with 512 short values, and validates
512 returned output bytes (256 samples), plus an untouched tail canary, before writing caller output. Frames are fixed and storage bounded.
A reset destroys/recreates algorithm state with the same configuration.

Explicit parameters override the vendor header's unrelated 8-channel/DOA/AINR defaults.
Software delay estimation EN_DELAY is always enabled. create(0) selects linear AEC only;
create(1) additionally enables Fastaec and conservative AES, disabling its hard/harmonic
suppression. Neither option enables automatic gain or neural denoising. Parameters are
owned by the bridge; do not call SDK parameter-free helpers on these embedded structures.

Playback reference must follow actual audio written for playback, be continuously
resampled to 16kHz, and aligned to capture using bounded buffering. This bridge alone
does not solve ALSA queue timing, clock drift, speaker nonlinearity, or near-end gating.
Real-device echo and double-talk validation remains necessary.

## Synthetic probe

`./aec_probe 0` then `./aec_probe 1` operates only on deterministic generated samples.
It simulates delayed echo, measures echo-only ERLE after settling, then estimates a
347Hz near-end tone's preserved amplitude during double talk. It also exercises reset.
There is no microphone, playback, cloud call, or audio-file output. Reported values are
experimental diagnostics, not a substitute for speech listening/real acoustic testing.
ARM probe execution is separate from successful cross-compilation; do not report an
unexecuted probe as passed.

## Vendor source and licensing boundary

BSP source: `external/common_algorithm/audio/rkaudio_algorithms/include/rkaudio_preprocess.h`;
API/channel/frame documentation: `doc/Rockchip_Developer_Guide_Microphone_Array_Tuning.pdf`,
pages 8–10. The SDK's `external/common_algorithm/LICENSE` permits source/binary redistribution
with attribution/disclaimer preservation and no endorsement (three-clause BSD-style terms).
No separate overriding license was found in this component. When distributing its binaries,
include that vendor copyright/license text; this repository does not silently relicense or
copy proprietary SDK headers/blobs. Review the license supplied with any replacement SDK.

Host ABI/lifetime tests (stubbed vendor, not signal-quality evidence):
`python3 scripts/audio-aec/test_host.py --sdk-include "$SDK/external/common_algorithm/audio/rkaudio_algorithms/include"`

Output-unit verification for this SDK ordinary lib64 binary: disassembly of
`rkaudio_preprocess_short` at 0x23848–0x23854 passes returned `w21` directly to
`memcpy` as its byte length; 0x2378c returns that value. BF initialization stores
`frame_samples << 1` at context offset 36 (0x22918/0x2292c), read into `w21` at
0x23948. Thus 512 means 256 int16 mono samples, not 512 samples. The bridge additionally
checks its guarded tail beyond those samples on every invocation. The previously
assumed sample-count return was incorrect and rejected valid output at frame zero.

## User-coordinated double-talk check

`double_talk_probe.py --run-local-double-talk-test --wav FIXED_MONO_WAV --library /absolute/librtctrl_aec.so --speech-root /absolute/speech-root`
requires prior user coordination and the board ALSA_CONFIG_PATH. It opens the microphone
for 17 seconds and plays the first up-to-eight seconds of the fixture twice. Use a fixture
at least eight seconds long (the current 7.895-second fixture also covers the scoring window).
It scores only capture frames 2–14 seconds after the first playback write, excluding startup/tail.
Before recording, local ASR rejects a fixture too similar to the fixed test sentence.
Captured raw/AEC/AEC+AES stay bounded in RAM, then use local RKNN ASR; no cloud request,
audio file or recognized transcript is emitted. Output is aggregate RMS/peak and matching counts.
The target is 今天天气不错，我想出去散步; ask the user to repeat it during playback.
Best substring edit distance is not whole-recording CER, exact matches are not recall without
a known repetition count, and mixed-speech energy reduction is not near-end preservation/ERLE.
This check supports a narrow intelligibility observation, not universal double-talk certification.
