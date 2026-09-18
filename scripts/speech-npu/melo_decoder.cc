// Persistent RV1126B Melo decoder adapter. No model/runtime installation.
#include "melo_decoder.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <exception>
#include <memory>
#include <rknn_api.h>
#include <vector>

namespace {
constexpr size_t kFrames = 256, kChannels = 192, kSamples = 131072;
constexpr std::array<unsigned, 6> kScales{{1, 8, 64, 128, 256, 512}};
thread_local char error_text[512] = {};
void error(const char* message, int code = 0) {
    std::snprintf(error_text, sizeof(error_text), "%s (code=%d)", message, code);
}
struct Decoder {
    rknn_context context = 0;
    std::array<std::vector<float>, 7> data;
    std::array<rknn_input, 7> inputs{};
    std::vector<float> result;
    ~Decoder() {
        if (context)
            rknn_destroy(context);
    }
};
bool shape(const rknn_tensor_attr& a, unsigned channels, unsigned length) {
    // RKNN may preserve the ONNX 3-D layout or insert a singleton spatial axis.
    if (a.n_elems != channels * length)
        return false;
    if (a.n_dims == 3)
        return a.dims[0] == 1 && a.dims[1] == channels && a.dims[2] == length;
    if (a.n_dims != 4 || a.dims[0] != 1)
        return false;
    if (a.fmt == RKNN_TENSOR_NHWC)
        return a.dims[3] == channels && ((a.dims[1] == 1 && a.dims[2] == length) ||
                                         (a.dims[1] == length && a.dims[2] == 1));
    return a.dims[1] == channels && ((a.dims[2] == 1 && a.dims[3] == length) ||
                                     (a.dims[2] == length && a.dims[3] == 1));
}
bool tensor(rknn_context context,
            unsigned index,
            bool output,
            const char* name,
            unsigned channels,
            unsigned length) {
    rknn_tensor_attr a{};
    a.index = index;
    int rc = rknn_query(context,
                        output ? RKNN_QUERY_OUTPUT_ATTR : RKNN_QUERY_INPUT_ATTR,
                        &a,
                        sizeof(a));
    if (rc != RKNN_SUCC) {
        error("tensor query failed", rc);
        return false;
    }
    if (std::strcmp(a.name, name) || !shape(a, channels, length) ||
        (a.type != RKNN_TENSOR_FLOAT16 && a.type != RKNN_TENSOR_FLOAT32)) {
        std::snprintf(error_text,
                      sizeof(error_text),
                      "unexpected %s tensor %u name=%s dims=%u [%u,%u,%u,%u] "
                      "elems=%u type=%d fmt=%d",
                      output ? "output" : "input",
                      index,
                      a.name,
                      a.n_dims,
                      a.dims[0],
                      a.dims[1],
                      a.dims[2],
                      a.dims[3],
                      a.n_elems,
                      a.type,
                      a.fmt);
        return false;
    }
    return true;
}
} // namespace
extern "C" {
const char* melo_decoder_error() {
    return error_text;
}
void* melo_decoder_create(const char* path) {
    error_text[0] = 0;
    if (!path || !path[0]) {
        error("empty model path");
        return nullptr;
    }
    try {
        std::unique_ptr<Decoder> d(new Decoder);
        int rc = rknn_init(&d->context, const_cast<char*>(path), 0, 0, nullptr);
        if (rc != RKNN_SUCC) {
            error("model initialization failed", rc);
            return nullptr;
        }
        rknn_input_output_num num{};
        rc = rknn_query(d->context, RKNN_QUERY_IN_OUT_NUM, &num, sizeof(num));
        if (rc != RKNN_SUCC) {
            error("IO query failed", rc);
            return nullptr;
        }
        if (num.n_input != 7 || num.n_output != 1) {
            error("expected seven inputs and one output");
            return nullptr;
        }
        if (!tensor(d->context, 0, false, "/Mul_10_output_0", kChannels, kFrames) ||
            !tensor(d->context, 0, true, "y", 1, kSamples))
            return nullptr;
        d->data[0].resize(kChannels * kFrames);
        for (unsigned i = 0; i < 6; i++) {
            char name[32];
            std::snprintf(name, sizeof(name), "mask_%u", kScales[i]);
            if (!tensor(d->context, i + 1, false, name, 1, kFrames * kScales[i]))
                return nullptr;
            d->data[i + 1].resize(kFrames * kScales[i]);
        }
        for (unsigned i = 0; i < 7; i++) {
            auto& in = d->inputs[i];
            in.index = i;
            in.type = RKNN_TENSOR_FLOAT32;
            in.fmt = RKNN_TENSOR_NCHW;
            in.pass_through = 0;
            in.buf = d->data[i].data();
            in.size = d->data[i].size() * sizeof(float);
        }
        d->result.resize(kSamples);
        return d.release();
    } catch (const std::exception& e) {
        error(e.what());
        return nullptr;
    } catch (...) {
        error("unknown create failure");
        return nullptr;
    }
}
int melo_decoder_run(void* opaque,
                     const float* latent,
                     unsigned valid_length,
                     float* output) {
    error_text[0] = 0;
    if (!opaque || !latent || !output || valid_length < 1 ||
        valid_length > kFrames) {
        error("invalid pointer or valid_length outside 1..256");
        return -1;
    }
    auto& d = *static_cast<Decoder*>(opaque);
    // Caller supplies [192,256]. Ignore padding, preventing stale/NaN tail
    // contamination.
    for (unsigned c = 0; c < kChannels; c++) {
        const float* src = latent + c * kFrames;
        float* dst = d.data[0].data() + c * kFrames;
        for (unsigned t = 0; t < valid_length; t++) {
            if (!std::isfinite(src[t])) {
                error("non-finite latent value");
                return -1;
            }
            dst[t] = src[t];
        }
        std::fill(dst + valid_length, dst + kFrames, 0.0f);
    }
    for (unsigned i = 0; i < 6; i++) {
        auto& mask = d.data[i + 1];
        auto split = mask.begin() + valid_length * kScales[i];
        std::fill(mask.begin(), split, 1.0f);
        std::fill(split, mask.end(), 0.0f);
    }
    int rc = rknn_inputs_set(d.context, 7, d.inputs.data());
    if (rc != RKNN_SUCC) {
        error("inputs_set failed", rc);
        return -1;
    }
    rc = rknn_run(d.context, nullptr);
    if (rc != RKNN_SUCC) {
        error("run failed", rc);
        return -1;
    }
    rknn_output out{};
    out.index = 0;
    out.want_float = 1;
    out.is_prealloc = 1;
    out.buf = d.result.data();
    out.size = kSamples * sizeof(float);
    rc = rknn_outputs_get(d.context, 1, &out, nullptr);
    if (rc != RKNN_SUCC) {
        error("outputs_get failed", rc);
        return -1;
    }
    bool valid = out.buf == d.result.data() && out.size == kSamples * sizeof(float);
    if (valid)
        for (float value : d.result)
            if (!std::isfinite(value)) {
                valid = false;
                break;
            }
    rc = rknn_outputs_release(d.context, 1, &out);
    if (rc != RKNN_SUCC) {
        error("outputs_release failed", rc);
        return -1;
    }
    if (!valid) {
        error("invalid output size/buffer/non-finite values");
        return -1;
    }
    std::memcpy(output, d.result.data(), kSamples * sizeof(float));
    return 0;
}
int melo_decoder_destroy(void* opaque) {
    error_text[0] = 0;
    if (!opaque)
        return 0;
    std::unique_ptr<Decoder> d(static_cast<Decoder*>(opaque));
    int rc = rknn_destroy(d->context);
    d->context = 0;
    if (rc != RKNN_SUCC) {
        error("destroy failed", rc);
        return -1;
    }
    return 0;
}
}
