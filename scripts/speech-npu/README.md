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
