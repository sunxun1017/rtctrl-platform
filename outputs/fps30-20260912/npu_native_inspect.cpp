#include <rknn_api.h>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>
#include <time.h>
static double thread_us() {
    timespec t{};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t)) throw std::runtime_error("thread clock failed");
    return t.tv_sec * 1000000.0 + t.tv_nsec / 1000.0;
}

using Clock = std::chrono::steady_clock;
static double us(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::micro>(b-a).count();
}
static void check(int code, const char* op) {
    if (code < 0) throw std::runtime_error(std::string(op)+" failed: "+std::to_string(code));
}
struct Context {
    rknn_context ctx = 0;
    ~Context() { if (ctx) rknn_destroy(ctx); }
};
int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("usage: npu_native_inspect model.rknn repeats");
        int repeats = std::stoi(argv[2]);
        if (repeats < 1 || repeats > 100000) throw std::runtime_error("repeats must be 1..100000");
        std::ifstream file(argv[1], std::ios::binary | std::ios::ate);
        if (!file) throw std::runtime_error("cannot open model");
        auto length = file.tellg();
        if (length <= 0 || static_cast<uint64_t>(length) > UINT32_MAX) throw std::runtime_error("invalid model size");
        std::vector<char> model(static_cast<size_t>(length));
        file.seekg(0); file.read(model.data(), length);
        if (!file) throw std::runtime_error("model read failed");
        Context context;
        check(rknn_init(&context.ctx, model.data(), static_cast<uint32_t>(model.size()), 0, nullptr), "init");
        rknn_input_output_num counts{};
        check(rknn_query(context.ctx, RKNN_QUERY_IN_OUT_NUM, &counts, sizeof(counts)), "counts");
        std::vector<rknn_tensor_attr> ia(counts.n_input), oa(counts.n_output);
        std::vector<std::vector<float>> input(counts.n_input), output(counts.n_output), reference(counts.n_output);
        std::vector<rknn_input> ins(counts.n_input);
        std::vector<std::vector<uint8_t>> input_u8(counts.n_input);
        auto attrs = [&](bool is_input, std::vector<rknn_tensor_attr>& attrs) {
            for (uint32_t i=0; i<attrs.size(); ++i) {
                auto& a=attrs[i]; a.index=i;
                check(rknn_query(context.ctx, is_input ? RKNN_QUERY_INPUT_ATTR : RKNN_QUERY_OUTPUT_ATTR, &a, sizeof(a)), "tensor attr");
                if (!a.n_elems || a.n_elems > UINT32_MAX/sizeof(float)) throw std::runtime_error("unsupported tensor size");
                std::cout << "tensor " << (is_input?"input":"output") << " index=" << i << " name=" << a.name << " elems=" << a.n_elems << " type=" << a.type << " fmt=" << a.fmt << " dims=";
                for (uint32_t d=0; d<a.n_dims; ++d) std::cout << a.dims[d] << ',';
                std::cout << '\n';
            }
        };
        attrs(true, ia); attrs(false, oa);
        rknn_sdk_version version{};
        int vr=rknn_query(context.ctx,RKNN_QUERY_SDK_VERSION,&version,sizeof(version));
        std::cout << "version_query_ret=" << vr;
        if (!vr) std::cout << " sdk=" << version.api_version << " driver=" << version.drv_version;
        std::cout << '\n';
        for (int native=0; native<2; ++native) for (int input_kind=0; input_kind<2; ++input_kind) {
            uint32_t count=input_kind?counts.n_input:counts.n_output;
            for (uint32_t i=0; i<count; ++i) {
                rknn_tensor_attr a{}; a.index=i;
                auto cmd=native?(input_kind?RKNN_QUERY_NATIVE_INPUT_ATTR:RKNN_QUERY_NATIVE_OUTPUT_ATTR):(input_kind?RKNN_QUERY_INPUT_ATTR:RKNN_QUERY_OUTPUT_ATTR);
                int ar=rknn_query(context.ctx,cmd,&a,sizeof(a));
                std::cout << "attr native=" << native << " input=" << input_kind << " index=" << i << " ret=" << ar;
                if (!ar) {
                    std::cout << " name=" << a.name << " type=" << get_type_string(a.type) << " fmt=" << get_format_string(a.fmt) << " qnt=" << get_qnt_type_string(a.qnt_type) << " zp=" << a.zp << " scale=" << a.scale << " fl=" << int(a.fl) << " elems=" << a.n_elems << " size=" << a.size << " size_with_stride=" << a.size_with_stride << " w_stride=" << a.w_stride << " h_stride=" << a.h_stride << " dims=";
                    for (uint32_t d=0; d<a.n_dims; ++d) std::cout << a.dims[d] << ',';
                }
                std::cout << '\n';
            }
        }
        std::cout << "native_execution=not_attempted normalization_and_packing_require_validation\n";
        for (uint32_t i=0; i<counts.n_input; ++i) {
            input[i].resize(ia[i].n_elems);
            for (size_t j=0; j<input[i].size(); ++j) input[i][j]=static_cast<float>((j*37+i*11)%256);
            input_u8[i].assign(input[i].begin(), input[i].end());
            ins[i].index=i; ins[i].buf=input[i].data(); ins[i].size=input[i].size()*sizeof(float);
            ins[i].type=RKNN_TENSOR_FLOAT32; ins[i].fmt=ia[i].fmt; ins[i].pass_through=0;
        }
        for (uint32_t i=0; i<counts.n_output; ++i) { output[i].resize(oa[i].n_elems); reference[i].resize(oa[i].n_elems); }
        std::cout << "input deterministic integer 0..255 float32 vs uint8; all outputs preallocated; no accuracy claim; timings_us\n";
        double maximum_error=0; bool reference_set=false;
        // Alternate modes per pair, reversing order each pair to limit drift.
        for (int pair=-3; pair<repeats; ++pair) {
            for (int slot=0; slot<2; ++slot) {
                bool use_u8=((pair+4)%2==0)?slot==1:slot==0;
                const bool prealloc=true;
                for (uint32_t i=0; i<counts.n_input; ++i) {
                    ins[i].type=use_u8?RKNN_TENSOR_UINT8:RKNN_TENSOR_FLOAT32;
                    ins[i].buf=use_u8?static_cast<void*>(input_u8[i].data()):static_cast<void*>(input[i].data());
                    ins[i].size=use_u8?input_u8[i].size():input[i].size()*sizeof(float);
                }
                std::vector<rknn_output> outs(counts.n_output);
                for (uint32_t i=0; i<counts.n_output; ++i) {
                    outs[i].index=i; outs[i].want_float=1; outs[i].is_prealloc=prealloc;
                    if (prealloc) { outs[i].buf=output[i].data(); outs[i].size=output[i].size()*sizeof(float); }
                }
                double c0=thread_us(); auto t0=Clock::now(); check(rknn_inputs_set(context.ctx, counts.n_input, ins.data()), "inputs_set");
                auto t1=Clock::now(); double c1=thread_us(); check(rknn_run(context.ctx, nullptr), "run");
                auto t2=Clock::now(); double c2=thread_us(); check(rknn_outputs_get(context.ctx, counts.n_output, outs.data(), nullptr), "outputs_get");
                auto t3=Clock::now(); double c3=thread_us();
                bool sizes_ok=true;
                for (uint32_t i=0; i<counts.n_output; ++i) {
                    size_t bytes=output[i].size()*sizeof(float);
                    if (!outs[i].buf || outs[i].size < bytes) { sizes_ok=false; continue; }
                    if (!prealloc) std::memcpy(output[i].data(), outs[i].buf, bytes);
                }
                auto t4=Clock::now();
                int released=rknn_outputs_release(context.ctx, counts.n_output, outs.data());
                auto t5=Clock::now(); check(released, "outputs_release");
                if (!sizes_ok) throw std::runtime_error("output missing or size too small");
                double error=0;
                for (uint32_t i=0; i<counts.n_output; ++i) for (size_t j=0; j<output[i].size(); ++j) {
                    float v=output[i][j];
                    if (!std::isfinite(v)) throw std::runtime_error("nonfinite output");
                    if (reference_set) error=std::max(error, std::abs(double(v)-reference[i][j]));
                    else reference[i][j]=v;
                }
                reference_set=true; maximum_error=std::max(maximum_error,error);
                if (pair>=0) std::cout << "sample pair=" << pair << " uint8=" << use_u8 << " input_us=" << us(t0,t1) << " run_us=" << us(t1,t2) << " get_us=" << us(t2,t3) << " copy_us=" << us(t3,t4) << " release_us=" << us(t4,t5) << " total_us=" << us(t0,t5) << " input_thread_cpu_us=" << c1-c0 << " run_thread_cpu_us=" << c2-c1 << " get_thread_cpu_us=" << c3-c2 << " max_abs_error=" << error << '\n';
            }
        }
        rknn_perf_run perf{}; int pr=rknn_query(context.ctx, RKNN_QUERY_PERF_RUN, &perf, sizeof(perf));
        std::cout << "perf_query_ret=" << pr; if (pr==0) std::cout << " run_duration_us=" << perf.run_duration; std::cout << '\n';
        rknn_mem_size mem{}; int mr=rknn_query(context.ctx, RKNN_QUERY_MEM_SIZE, &mem, sizeof(mem));
        std::cout << "mem_query_ret=" << mr; if (mr==0) std::cout << " weights=" << mem.total_weight_size << " internal=" << mem.total_internal_size << " dma=" << mem.total_dma_allocated_size; std::cout << '\n';
        std::cout << "result finite=1 max_abs_error=" << maximum_error << " exact_equal=" << (maximum_error==0) << '\n';
        return maximum_error <= 1e-5 ? 0 : 3;
    } catch (const std::exception& e) { std::cerr << "ERROR " << e.what() << '\n'; return 1; }
}
