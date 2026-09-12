# Optional TurboJPEG preview encoder

`rtctrl_face_video --jpeg-encoder opencv|turbojpeg` defaults to `opencv`.
TurboJPEG support is compiled only when CMake finds `turbojpeg.h` through
`RTCTRL_TURBOJPEG_INCLUDE_DIR`. Without that header the normal OpenCV build
still works; selecting TurboJPEG reports that support was not compiled.
At runtime TurboJPEG opens the existing `libturbojpeg.so.0` with `dlopen`.
A missing library/symbol is an explicit startup error; no silent fallback.

The encoder accepts strided BGR CV_8UC3 images, reuses one compressor and a
maximum JPEG buffer for the current dimensions, and selects 4:2:0 plus accurate
DCT. It does not enable fast DCT. Each returned JPEG vector independently owns
its bytes so HTTP consumers can retain a previous frame. The encoder has one
owner thread. Changing dimensions recalculates the capacity. `encode_ms` in
status covers encoding and the independent output copy, excluding drawing,
JSON construction, HTTP publication, and inference. Existing `processing_ms`
continues to exclude JPEG encoding.

## Header provenance

The observed board library embeds libjpeg-turbo 2.1.5 (build 20260321), with
SHA256 `b126e20355d2152cfe65ee261e49cf7620c29c69b65c8932b2277c9100dc863b`.
The SDK's separate rockit library was 2.0.2 and is not the deployed reference.

The corresponding official public header can be cached outside repository
history at `.deps/libjpeg-turbo-2.1.5/turbojpeg.h`:

- Source: https://raw.githubusercontent.com/libjpeg-turbo/libjpeg-turbo/2.1.5/turbojpeg.h
- Header SHA256: `ebe6e99e43eaa17f2f47efe6dcd5c7bf08bc2feaab6670f6063fbddbc6cba654`

Pass `-DRTCTRL_TURBOJPEG_INCLUDE_DIR=/absolute/path/to/.deps/libjpeg-turbo-2.1.5`
to CMake. CMake does not download dependencies. The official header retains its
license; no vendor declarations are copied into production source. Pin a proper
submodule if this dependency later needs to become a tracked third-party source.

The native encoder tests use the official header and a small fake runtime to
check runtime loading, source stride, dimensions, accurate-DCT/no-reallocation
flags, failure propagation and ownership. Those tests do not replace the real
board encoder comparison.
