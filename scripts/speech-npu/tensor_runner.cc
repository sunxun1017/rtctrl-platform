#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <rknn_api.h>
#include <string>
#include <vector>

static void check(int code, const char* op) {
    if (code != RKNN_SUCC) {
        std::fprintf(stderr, "%s failed: %d\n", op, code);
        std::exit(1);
    }
}
static void attrs(const char* side, const rknn_tensor_attr& a) {
    std::printf("%s index=%u name=%s fmt=%d type=%d elems=%u bytes=%u dims=",
                side,
                a.index,
                a.name,
                a.fmt,
                a.type,
                a.n_elems,
                a.size);
    for (unsigned j = 0; j < a.n_dims; j++)
        std::printf("%s%u", j ? "," : "", a.dims[j]);
    std::puts("");
}
int main(int argc, char** argv) {
    if (argc < 5) {
        std::fprintf(stderr,
                     "usage: %s model.rknn output_prefix rounds input0.f32 "
                     "[input1.f32 ...]\n",
                     argv[0]);
        return 2;
    }
    char* end = nullptr;
    long rounds = std::strtol(argv[3], &end, 10);
    if (!end || *end || rounds < 1 || rounds > 100) {
        std::fprintf(stderr, "rounds must be 1..100\n");
        return 2;
    }
    rknn_context ctx = 0;
    auto init_start = std::chrono::steady_clock::now();
    check(rknn_init(&ctx, argv[1], 0, 0, nullptr), "rknn_init");
    std::printf("init_ms=%.3f\n",
                std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - init_start)
                    .count());
    rknn_sdk_version ver{};
    check(rknn_query(ctx, RKNN_QUERY_SDK_VERSION, &ver, sizeof(ver)),
          "query_version");
    std::printf("runtime=%s driver=%s\n", ver.api_version, ver.drv_version);
    rknn_input_output_num num{};
    check(rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &num, sizeof(num)), "query_num");
    if (num.n_input != unsigned(argc - 4) || num.n_input > 128 ||
        num.n_output > 128) {
        std::fprintf(
            stderr,
            "input count mismatch or excessive IO count: expected=%u provided=%d\n",
            num.n_input,
            argc - 4);
        rknn_destroy(ctx);
        return 2;
    }
    std::vector<std::vector<float>> input_data(num.n_input);
    std::vector<rknn_input> inputs(num.n_input);
    for (unsigned i = 0; i < num.n_input; i++) {
        rknn_tensor_attr a{};
        a.index = i;
        check(rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &a, sizeof(a)), "query_input");
        attrs("input", a);
        if (a.n_elems == 0 || a.n_elems > 64 * 1024 * 1024) {
            std::fprintf(stderr, "invalid input elems\n");
            return 2;
        }
        std::ifstream f(argv[4 + i], std::ios::binary | std::ios::ate);
        const auto bytes = size_t(a.n_elems) * sizeof(float);
        if (!f || f.tellg() != std::streamoff(bytes)) {
            std::fprintf(stderr,
                         "input byte mismatch: %s expected=%zu\n",
                         argv[4 + i],
                         bytes);
            return 2;
        }
        input_data[i].resize(a.n_elems);
        f.seekg(0);
        f.read(reinterpret_cast<char*>(input_data[i].data()), bytes);
        if (!f) {
            std::fprintf(stderr, "input read failure\n");
            return 2;
        }
        inputs[i].index = i;
        inputs[i].buf = input_data[i].data();
        inputs[i].size = bytes;
        inputs[i].type = RKNN_TENSOR_FLOAT32;
        inputs[i].fmt = RKNN_TENSOR_NCHW;
        inputs[i].pass_through = 0;
    }
    std::vector<rknn_tensor_attr> output_attrs(num.n_output);
    for (unsigned i = 0; i < num.n_output; i++) {
        auto& a = output_attrs[i];
        a.index = i;
        check(rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &a, sizeof(a)),
              "query_output");
        attrs("output", a);
    }
    for (long round = -1; round < rounds; round++) {
        std::vector<rknn_output> outputs(num.n_output);
        for (unsigned i = 0; i < num.n_output; i++) {
            outputs[i].index = i;
            outputs[i].want_float = 1;
            outputs[i].is_prealloc = 0;
        }
        auto start = std::chrono::steady_clock::now();
        check(rknn_inputs_set(ctx, num.n_input, inputs.data()), "inputs_set");
        auto run_start = std::chrono::steady_clock::now();
        check(rknn_run(ctx, nullptr), "rknn_run");
        auto run_end = std::chrono::steady_clock::now();
        check(rknn_outputs_get(ctx, num.n_output, outputs.data(), nullptr),
              "outputs_get");
        auto finish = std::chrono::steady_clock::now();
        std::printf(
            "round=%ld warmup=%d run_ms=%.3f io_run_ms=%.3f\n",
            round,
            round < 0,
            std::chrono::duration<double, std::milli>(run_end - run_start).count(),
            std::chrono::duration<double, std::milli>(finish - start).count());
        for (unsigned i = 0; i < num.n_output; i++) {
            auto bytes = size_t(output_attrs[i].n_elems) * sizeof(float);
            if (!outputs[i].buf || outputs[i].size != bytes) {
                std::fprintf(stderr,
                             "output %u bytes mismatch: got=%u expected=%zu\n",
                             i,
                             outputs[i].size,
                             bytes);
                return 1;
            }
            if (round == rounds - 1) {
                auto path = std::string(argv[2]) + "." + std::to_string(i) + ".f32";
                std::ofstream f(path, std::ios::binary);
                f.write(reinterpret_cast<char*>(outputs[i].buf), bytes);
                f.close();
                if (!f) {
                    std::fprintf(stderr, "output write failure: %s\n", path.c_str());
                    return 1;
                }
                std::printf("saved=%s bytes=%zu\n", path.c_str(), bytes);
            }
        }
        check(rknn_outputs_release(ctx, num.n_output, outputs.data()),
              "outputs_release");
        std::fflush(stdout);
    }
    check(rknn_destroy(ctx), "destroy");
    return 0;
}
