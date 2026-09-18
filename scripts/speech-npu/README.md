# RV1126B speech NPU probes

These are experimental executables. The Zipformer runner can also be selected by the
companion worker through the opt-in `local_asr_backend=rknn` configuration.
They do not record a microphone, modify board services, or install RKNN runtime libraries.
Model conversion and numerical/board validation remain separate steps.

## Reproducible cross-build

Use the ALIENTEK RV1126B SDK aarch64 GCC 10.3.1 toolchain and its RKNN API headers/library.
The tested official Model Zoo revision is `bad6c7334531becaf90a561988519b7bec34d0ab`:

```bash
git clone --filter=blob:none --no-checkout https://github.com/airockchip/rknn_model_zoo.git work/rknn_model_zoo
git -C work/rknn_model_zoo sparse-checkout set examples/zipformer 3rdparty utils
git -C work/rknn_model_zoo checkout bad6c7334531becaf90a561988519b7bec34d0ab

# Set this to your ALIENTEK SDK directory.
SDK=/absolute/path/to/atk_dlrv1126b_linux6.1_sdk
TOOLCHAIN="$SDK/prebuilts/gcc/linux-x86/aarch64/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu"
cmake -S scripts/speech-npu -B work/speech-npu-build \
  -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DCMAKE_C_COMPILER="$TOOLCHAIN-gcc" -DCMAKE_CXX_COMPILER="$TOOLCHAIN-g++" \
  -DCMAKE_BUILD_TYPE=Release \
  -DMODEL_ZOO_ROOT="$PWD/work/rknn_model_zoo" \
  -DRKNN_SDK_ROOT="$SDK/external/rknpu2/runtime/Linux/librknn_api"
cmake --build work/speech-npu-build -j2
```

`MODEL_ZOO_ROOT` is optional when building only the tensor probe. It supplies upstream
Zipformer sources plus static libsndfile/kaldi-native-fbank libraries for the ASR probe.
No upstream checkout, model, fixture, binary or runtime library belongs in this directory.
The tested ELF interpreter is `/lib/ld-linux-aarch64.so.1`; inspect `readelf -d/-V` before
using another SDK. The ASR probe requires GLIBC up to 2.29 and GLIBCXX up to 3.4.21.

## ASR

Copy the executable, RV1126B-converted encoder/decoder/joiner, and upstream
`examples/zipformer/model/{vocab.txt,test.wav}` into an isolated board test directory.
Keep the vocabulary at `./model/vocab.txt`, relative to the working directory:

```bash
./rknn_zipformer_demo encoder.rknn decoder.rknn joiner.rknn model/test.wav
```

The public WAV expected text is: 对我做了介绍那么我想说的是大家如果对我的研究感兴趣呢

`zipformer_main.cc` derives from the above revision's Apache-2.0 example and retains
its copyright/license notice. Its only functional change is returning nonzero on
initialization/inference failure instead of upstream's unconditional success.
The upstream RTF denominator includes tail padding; for comparisons divide measured
inference time by original WAV duration. Inference timing includes CPU filterbank and
greedy decode, but excludes model initialization. This is a one-shot cold-process probe.

## Generic tensors / TTS decoder

```bash
./rknn_tensor_runner decoder-l16.rknn output-l16 5 latent-l16.f32 speaker.f32
```

Inputs follow queried model input order and must be little-endian float32 NCHW, exactly
`n_elems * 4` bytes. Inputs use `pass_through=0`. Output requests use `want_float=1` and
are validated for exact size. The final iteration saves `output-l16.0.f32`, etc.
The probe prints runtime/driver versions and tensor attributes, warms up once, then runs
1–100 measured iterations. `run_ms` covers RKNN execution; `io_run_ms` additionally
covers inputs_set and outputs_get. Failed RKNN calls, invalid byte counts, and I/O errors
exit nonzero. Recurrent state management is not implemented by this generic probe.

For the L16 AISHELL3 decoder fixture, inputs are latent `[1,96,16]` and speaker
`[1,256,1]`; expected output is `[1,1,4096]` (16384 bytes). Compare against the corresponding
ONNX reference using identical inputs; timing success does not establish audio quality.

Use the existing system `librknnrt.so`. Do not set `LD_LIBRARY_PATH` to Model Zoo's bundled
runtime, and do not replace the board runtime for these probes.


## Whole-sentence comparison

`make-sentence-fixtures.py MODEL_DIR OUTPUT_DIR` requires isolated host packages
sherpa-onnx 1.13.8, ONNX and ONNX Runtime. It captures actual frontend token IDs with
an instrumentation-only graph, asserts one frontend callback batch, then exports
full CPU waveform and its latent/speaker inputs. Do not concatenate multiple
frontend batches. Random generation means regenerated lengths can change; frozen
fixtures are not overwritten.

For each fixture, read latent_length from meta.json, then:

```bash
python convert-vits-decoder.py MODEL_DIR/model.onnx MODEL_OUTPUT --length LENGTH
# Copy the resulting model and matching latent.f32 / speaker.f32 to the board.
./rknn_tensor_runner decoder-lLENGTH.rknn npu 5 latent.f32 speaker.f32
# Copy npu.0.f32 back to the host.
python compare-sentence.py reference.f32 npu.0.f32 comparison
```

The compare script checks sample count/finiteness and records unnormalized
waveform error, correlation, clipping and PCM16 listening files at native 8 kHz.
This is a whole-sentence, fixed-shape probe; it does not validate arbitrary-length
production synthesis or perceptual quality. See ../../docs/verification-tts-sentences-20260918.md.


## Naturalness auditions

`tts-audition.py KIND MODEL_DIR OUTPUT_WAV TEXT` supports `aishell3`, `melo`,
and `kokoro` with the existing sherpa-onnx 1.13.8 host environment. Choose the
speaker explicitly (for example Kokoro v1.1-zh sid3); optional `--speed` and
`--duration-noise` only change model inputs, never remove phonemes or splice audio.
Each WAV gets a JSON sidecar with model hash, parameters, machine and timings.
Host timings do not establish RV1126B performance. It refuses to overwrite WAVs
and does not change any running service. Naturalness requires listening, not
waveform correlation or a shorter duration. See the user-rejected candidates in
../../docs/verification-tts-naturalness-20260918.md.

## Persistent Melo decoder shared library

The same configured cross-build provides `cmake --build work/speech-npu-build --target melo_decoder`.
The resulting `libmelo_decoder.so` uses the existing system RKNN runtime. Its C ABI is in
`melo_decoder.h`: create(path), run(handle, latent, valid_length, output), destroy(handle),
and thread-local error text. Check NULL / nonzero returns after every operation.

This adapter accepts only the masked bucket-256 model contract: latent `/Mul_10_output_0`
`[1,192,256]`, masks `mask_1,mask_8,mask_64,mask_128,mask_256,mask_512`, and output `y`
`[1,1,131072]`. It checks queried names, dimensions, types, and element counts at creation.
Singleton axes inserted by RKNN are accepted explicitly. All six masks are generated
inside C++, and latent padding beyond valid_length is zeroed. Input/output storage is
allocated once; model context persists across calls. Each run requests float32 NCHW input
and float32 output, validates finite values, and releases RKNN output ownership.

The caller must supply full 192*256 and 131072 float buffers, serialize calls per handle,
and trim returned audio to valid_length*512 samples. Destroy a handle exactly once.
Length 0 or >256 is rejected; this library does not implement chunk overlap or text frontend.
It does not replace the application's current TTS by itself. Cross-compilation alone does
not establish numerical equivalence, latency, stability, or listening quality.


## Accepted Melo hybrid on RV1126B

`convert-melo.py --source /path/model.onnx --output-dir /path/output --build`
extracts the exact CPU prefix and speaker-row-1 masked decoder, runs FP32 mask checks,
then builds RV1126B FP16 RKNN. Conversion writes a hash/version manifest; model files
are not committed. `validate-melo-chunks.py --model-dir /path/output --output-dir /path/reports`
checks the halo proof and stitched waveform against the exact decoder.

Install prefix.onnx, decoder-masked-256.rknn and libmelo_decoder.so under
`<local_speech_root>/melo-npu/`; keep official tokens.txt, lexicon.txt, dict/, date.fst,
number.fst, phone.fst and LICENSE under `<local_speech_root>/vits-melo-tts-zh_en/`.
Use `local_tts_kind=melo_npu`, speaker0. The full CPU model is needed only for `melo`.
Do not replace system librknnrt. Preserve the previous voice configuration/model for rollback.

Python adapter keeps complete sherpa batches, uses 256-frame decoder windows with
16-frame context, then applies upstream silence compression once per batch.
See ../../docs/verification-tts-naturalness-20260918.md for board results and limitations.
