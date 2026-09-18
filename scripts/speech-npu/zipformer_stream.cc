// Streaming adapter for the pinned Apache-2.0 Rockchip Zipformer example.
// Reuses its model-specific greedy step without resetting encoder caches between
// chunks.
#include "stream_protocol.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <memory>
#include <rknn_api.h>
#include <signal.h>
#include <stdexcept>
#include <unistd.h>

// Upstream preallocates output buffers. Release RKNN output bookkeeping every run.
static int stream_outputs_get(rknn_context ctx,
                              uint32_t count,
                              rknn_output* outputs,
                              rknn_output_extend* extend) {
    int rc = rknn_outputs_get(ctx, count, outputs, extend);
    if (rc != RKNN_SUCC)
        return rc;
    return rknn_outputs_release(ctx, count, outputs);
}
#define rknn_outputs_get stream_outputs_get
#include "rknpu2/zipformer.cc"
#undef rknn_outputs_get

namespace {
void require(bool condition, const char* message) {
    if (!condition)
        throw std::runtime_error(message);
}
struct Stream {
    rknn_zipformer_context_t ctx{};
    VocabEntry vocab[VOCAB_NUM]{};
    std::unique_ptr<knf::OnlineFbank> fbank;
    std::vector<std::string> tokens;
    std::vector<float> timestamps;
    int processed = 0, frame_offset = 0;
    unsigned samples = 0;
    bool finished = false;
    ~Stream() {
        for (auto* model :
             {&ctx.encoder_context, &ctx.decoder_context, &ctx.joiner_context}) {
            if (model->inputs) {
                for (unsigned i = 0; i < model->io_num.n_input; i++)
                    free(model->inputs[i].buf);
                free(model->inputs);
            }
            if (model->outputs) {
                for (unsigned i = 0; i < model->io_num.n_output; i++)
                    free(model->outputs[i].buf);
                free(model->outputs);
            }
            if (model->rknn_ctx)
                rknn_destroy(model->rknn_ctx);
            free(model->input_attrs);
            free(model->output_attrs);
        }
        for (auto& entry : vocab)
            free(entry.token);
    }
    void init(int argc, char** argv) {
        require(argc == 5,
                "usage: rknn_zipformer_stream encoder.rknn decoder.rknn joiner.rknn "
                "vocab.txt");
        require(read_vocab(argv[4], vocab) == 0, "cannot read vocabulary");
        for (unsigned i = 0; i < JOINER_OUTPUT_SIZE; i++)
            require(vocab[i].token != nullptr, "incomplete vocabulary");
        rknn_app_context_t* models[] = {
            &ctx.encoder_context, &ctx.decoder_context, &ctx.joiner_context};
        for (unsigned i = 0; i < 3; i++) {
            require(init_zipformer_model(argv[i + 1], models[i]) == 0,
                    "model initialization failed");
            auto& model = *models[i];
            require(model.io_num.n_input > 0 && model.io_num.n_input <= 128 &&
                        model.io_num.n_output > 0 && model.io_num.n_output <= 128,
                    "unsupported tensor count");
            for (unsigned j = 0; j < model.io_num.n_input; j++)
                require(model.input_attrs[j].type == RKNN_TENSOR_FLOAT16 ||
                            model.input_attrs[j].type == RKNN_TENSOR_INT64,
                        "unsupported input type");
            for (unsigned j = 0; j < model.io_num.n_output; j++)
                require(model.output_attrs[j].type == RKNN_TENSOR_FLOAT16 ||
                            model.output_attrs[j].type == RKNN_TENSOR_INT64,
                        "unsupported output type");
            model.inputs = static_cast<rknn_input*>(
                calloc(model.io_num.n_input, sizeof(rknn_input)));
            model.outputs = static_cast<rknn_output*>(
                calloc(model.io_num.n_output, sizeof(rknn_output)));
            require(model.inputs && model.outputs,
                    "IO descriptor allocation failed");
            size_t total_bytes = 0;
            for (unsigned j = 0; j < model.io_num.n_input; j++) {
                const auto& attr = model.input_attrs[j];
                auto& in = model.inputs[j];
                require(attr.n_elems > 0 && attr.n_elems <= 4 * 1024 * 1024,
                        "input elements out of bounds");
                in.index = j;
                in.type = attr.type == RKNN_TENSOR_FLOAT16 ? RKNN_TENSOR_FLOAT32
                                                           : RKNN_TENSOR_INT64;
                in.fmt = attr.fmt;
                in.size = attr.n_elems * (in.type == RKNN_TENSOR_FLOAT32 ? 4 : 8);
                total_bytes += in.size;
                require(total_bytes <= 32 * 1024 * 1024,
                        "model IO memory exceeds bound");
                in.buf = calloc(1, in.size);
                require(in.buf, "input allocation failed");
            }
            for (unsigned j = 0; j < model.io_num.n_output; j++) {
                const auto& attr = model.output_attrs[j];
                auto& out = model.outputs[j];
                require(attr.n_elems > 0 && attr.n_elems <= 4 * 1024 * 1024,
                        "output elements out of bounds");
                out.index = j;
                out.want_float = attr.type == RKNN_TENSOR_FLOAT16;
                out.is_prealloc = 1;
                out.size = attr.n_elems * (out.want_float ? 4 : 8);
                total_bytes += out.size;
                require(total_bytes <= 32 * 1024 * 1024,
                        "model IO memory exceeds bound");
                out.buf = calloc(1, out.size);
                require(out.buf, "output allocation failed");
            }
            for (unsigned j = 0; j < model.io_num.n_input; j++)
                require(model.inputs[j].buf, "input allocation failed");
            for (unsigned j = 0; j < model.io_num.n_output; j++)
                require(model.outputs[j].buf, "output allocation failed");
        }
        require(ctx.encoder_context.io_num.n_input ==
                    ctx.encoder_context.io_num.n_output,
                "encoder state count mismatch");
        require(ctx.encoder_context.input_attrs[0].n_elems == ENCODER_INPUT_SIZE &&
                    ctx.encoder_context.output_attrs[0].n_elems ==
                        ENCODER_OUTPUT_SIZE,
                "unsupported encoder dimensions");
        require(ctx.decoder_context.io_num.n_input == 1 &&
                    ctx.decoder_context.io_num.n_output == 1 &&
                    ctx.decoder_context.input_attrs[0].n_elems == 2 &&
                    ctx.decoder_context.output_attrs[0].n_elems == 512,
                "unsupported decoder dimensions");
        require(ctx.joiner_context.io_num.n_input == 2 &&
                    ctx.joiner_context.io_num.n_output == 1 &&
                    ctx.joiner_context.input_attrs[0].n_elems == 512 &&
                    ctx.joiner_context.input_attrs[1].n_elems == 512 &&
                    ctx.joiner_context.output_attrs[0].n_elems == 6254,
                "unsupported joiner dimensions");
        for (unsigned i = 1; i < ctx.encoder_context.io_num.n_input; i++)
            require(ctx.encoder_context.inputs[i].size ==
                        ctx.encoder_context.outputs[i].size,
                    "encoder cache size mismatch");
        reset();
    }
    void reset() {
        for (auto* model :
             {&ctx.encoder_context, &ctx.decoder_context, &ctx.joiner_context}) {
            for (unsigned i = 0; i < model->io_num.n_input; i++)
                memset(model->inputs[i].buf, 0, model->inputs[i].size);
            for (unsigned i = 0; i < model->io_num.n_output; i++)
                memset(model->outputs[i].buf, 0, model->outputs[i].size);
        }
        knf::FbankOptions options;
        options.frame_opts.samp_freq = 16000;
        options.mel_opts.num_bins = 80;
        options.mel_opts.high_freq = -400;
        options.frame_opts.dither = 0;
        options.frame_opts.snip_edges = false;
        fbank.reset(new knf::OnlineFbank(options));
        tokens.clear();
        timestamps.clear();
        processed = frame_offset = 0;
        samples = 0;
        finished = false;
    }
    void step() {
        auto& enc = ctx.encoder_context;
        auto& dec = ctx.decoder_context;
        require(get_kbank_frames(fbank.get(),
                                 processed,
                                 N_SEGMENT,
                                 static_cast<float*>(enc.inputs[0].buf)) == 0,
                "fbank incomplete segment");
        require(greedy_search(&ctx,
                              static_cast<float*>(enc.inputs[0].buf),
                              static_cast<float*>(enc.outputs[0].buf),
                              static_cast<float*>(dec.outputs[0].buf),
                              static_cast<int64_t*>(dec.inputs[0].buf),
                              static_cast<float*>(ctx.joiner_context.outputs[0].buf),
                              vocab,
                              tokens,
                              timestamps,
                              processed,
                              frame_offset) == 0,
                "RKNN decode failed");
        processed += N_OFFSET;
        require(text().size() <= 4096, "transcript exceeds 4096 bytes");
    }
    void accept(const std::vector<unsigned char>& bytes) {
        require(!finished, "reset required after finish");
        require(samples + bytes.size() / 2 <= 480000,
                "utterance exceeds 30 seconds");
        std::vector<float> values(bytes.size() / 2);
        for (size_t i = 0; i < values.size(); i++)
            values[i] = static_cast<int16_t>(unsigned(bytes[i * 2]) |
                                             (unsigned(bytes[i * 2 + 1]) << 8)) /
                        32768.0f;
        samples += values.size();
        fbank->AcceptWaveform(16000, values.data(), values.size());
        while (fbank->NumFramesReady() - processed >= N_SEGMENT)
            step();
    }
    void finish() {
        require(!finished, "already finished; reset required");
        // NumFrames(flush=true) counts the real waveform's reflected final frame.
        // Padding must never become the decode target: 97..102 pending real frames
        // require TWO advances of 96, although each encoder window reads 103.
        knf::FrameExtractionOptions options;
        options.samp_freq = 16000;
        options.snip_edges = false;
        const unsigned real_frames = knf::NumFrames(samples, options, true);
        const unsigned steps = speech_stream::flush_steps(processed, real_frames);
        if (steps) {
            const int required_frames =
                processed + (steps - 1) * N_OFFSET + N_SEGMENT;
            const int missing =
                std::max(0, required_frames - fbank->NumFramesReady());
            std::vector<float> zeros((missing + 2) * 160, 0.0f);
            fbank->AcceptWaveform(16000, zeros.data(), zeros.size());
        }
        fbank->InputFinished();
        for (unsigned i = 0; i < steps; ++i)
            step();
        finished = true;
    }
    std::string text() const {
        std::string result;
        for (const auto& token : tokens)
            result += token;
        return result;
    }
    void reply(FILE* output, const char* type) {
        double blank = std::max(
            0.0,
            (frame_offset - (timestamps.empty() ? 0 : timestamps.back() + 1)) * .04);
        std::string reason =
            samples >= 480000
                ? "limit"
                : (!tokens.empty() && blank >= 1.2
                       ? "silence"
                       : (tokens.empty() && samples >= 80000 ? "silence" : ""));
        std::string escaped = speech_stream::quote(text());
        require(std::fprintf(
                    output,
                    "{\"type\":\"%s\",\"text\":%s,\"samples\":%u,\"audio_s\":%.6f,"
                    "\"trailing_blank_s\":%.6f,\"endpoint\":%s,\"reason\":\"%s\"}\n",
                    type,
                    escaped.c_str(),
                    samples,
                    samples / 16000.0,
                    blank,
                    reason.empty() ? "false" : "true",
                    reason.c_str()) >= 0,
                "response write failed");
        require(std::fflush(output) == 0, "response flush failed");
    }
};
} // namespace
int main(int argc, char** argv) {
    signal(SIGPIPE, SIG_IGN);
    int fd = dup(STDOUT_FILENO);
    if (fd < 0 || dup2(STDERR_FILENO, STDOUT_FILENO) < 0)
        return 1;
    FILE* output = fdopen(fd, "w");
    if (!output) {
        close(fd);
        return 1;
    }
    int status = 0;
    try {
        Stream stream;
        stream.init(argc, argv);
        fprintf(output,
                "{\"type\":\"ready\",\"sample_rate\":16000,\"max_audio_s\":30}\n");
        fflush(output);
        speech_stream::Request request;
        while (speech_stream::read_request(std::cin, request)) {
            if (request.opcode == 1) {
                stream.accept(request.payload);
                stream.reply(output, "partial");
            } else if (request.opcode == 2) {
                stream.finish();
                stream.reply(output, "final");
            } else if (request.opcode == 3) {
                stream.reset();
                stream.reply(output, "reset");
            } else {
                stream.reply(output, "quit");
                break;
            }
        }
    } catch (const std::exception& error) {
        fprintf(output,
                "{\"type\":\"error\",\"error\":%s}\n",
                speech_stream::quote(error.what()).c_str());
        fflush(output);
        status = 1;
    }
    fclose(output);
    return status;
}
