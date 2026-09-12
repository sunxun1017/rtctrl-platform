// Host-only contract test: these SDK substitutes never execute an RKNN model.
#include "rtctrl/adapters/rknn/backend.hpp"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool condition, const char* message) {
    if (!condition)
        throw std::runtime_error(message);
}
struct FakeSdk {
    bool native = false, bad_stride = false, fail_sync = false, fail_bind = false;
    int mem_destroys = 0, syncs = 0;
    std::vector<unsigned short> native_values;
    int queries = 0;
    int sets = 0;
    int runs = 0;
    int destroys = 0;
    int gets = 0;
    int releases = 0;
    bool uint8_input = false;
    bool fail_get = false;
    bool fail_release = false;
    bool bad_output_size = false;
    bool bad_output_shape = false;
    bool float16_input = false;
    bool zero_outputs = false;
    enum class BadAttr { None, Type, Rank, ZeroDim, Overflow, ElementCount };
    BadAttr bad_attr = BadAttr::None;
    bool fail_query = false;
    bool fail_set = false;
    bool fail_run = false;
    std::vector<std::vector<float>> submitted;
} sdk;
} // namespace
extern "C" {
int rknn_init(rknn_context* context, void*, uint32_t, uint32_t, rknn_init_extend*) {
    *context = 42;
    return RKNN_SUCC;
}
int rknn_destroy(rknn_context context) {
    require(context == 42, "destroy receives owned context");
    ++sdk.destroys;
    return RKNN_SUCC;
}
int rknn_query(rknn_context, rknn_query_cmd cmd, void* info, uint32_t size) {
    ++sdk.queries;
    if (sdk.fail_query)
        return -1;
    if (cmd == RKNN_QUERY_IN_OUT_NUM) {
        require(size == sizeof(rknn_input_output_num), "I/O query size");
        auto* count = static_cast<rknn_input_output_num*>(info);
        count->n_input = sdk.native ? 1 : 2;
        count->n_output = sdk.zero_outputs ? 0 : 1;
    } else if (cmd == RKNN_QUERY_NATIVE_INPUT_ATTR ||
               (sdk.native && cmd == RKNN_QUERY_INPUT_ATTR)) {
        auto* a = static_cast<rknn_tensor_attr*>(info);
        a->n_dims = 4;
        a->dims[0] = 1;
        a->dims[1] = 1;
        a->dims[2] = 2;
        a->dims[3] = 3;
        a->n_elems = 6;
        a->fmt = RKNN_TENSOR_NHWC;
        a->type = RKNN_TENSOR_FLOAT16;
        a->size = 12;
        a->size_with_stride = sdk.bad_stride ? 16 : 12;
        a->w_stride = 2;
        a->qnt_type = RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC;
        a->zp = 0;
        a->scale = 1;
    } else if (cmd == RKNN_QUERY_INPUT_ATTR || cmd == RKNN_QUERY_OUTPUT_ATTR) {
        require(size == sizeof(rknn_tensor_attr), "attribute query size");
        auto* attr = static_cast<rknn_tensor_attr*>(info);
        require(attr->index < (cmd == RKNN_QUERY_INPUT_ATTR ? 2u : 1u),
                "attribute index");
        attr->n_dims = 2;
        attr->dims[0] = 1;
        attr->dims[1] = attr->index == 0 ? 3 : 2;
        attr->n_elems = attr->dims[1];
        attr->type =
            sdk.float16_input
                ? RKNN_TENSOR_FLOAT16
                : RKNN_TENSOR_INT8; // Deliberately differs from public float input.
        attr->size = attr->n_elems;
        attr->fmt = RKNN_TENSOR_UNDEFINED;
        if (cmd == RKNN_QUERY_OUTPUT_ATTR && sdk.bad_output_shape)
            ++attr->n_elems;
        switch (sdk.bad_attr) {
            case FakeSdk::BadAttr::Type:
                attr->type = RKNN_TENSOR_INT64;
                break;
            case FakeSdk::BadAttr::Rank:
                attr->n_dims = RKNN_MAX_DIMS + 1;
                break;
            case FakeSdk::BadAttr::ZeroDim:
                attr->dims[0] = 0;
                attr->n_elems = 0;
                break;
            case FakeSdk::BadAttr::Overflow:
                attr->dims[0] = UINT32_MAX;
                attr->dims[1] = UINT32_MAX;
                break;
            case FakeSdk::BadAttr::ElementCount:
                ++attr->n_elems;
                break;
            case FakeSdk::BadAttr::None:
                break;
        }
    } else {
        throw std::runtime_error("unexpected SDK query");
    }
    return RKNN_SUCC;
}
int rknn_inputs_set(rknn_context, uint32_t count, rknn_input inputs[]) {
    ++sdk.sets;
    require(count == 2, "all inputs submitted together");
    sdk.submitted.clear();
    for (uint32_t i = 0; i < count; ++i) {
        require(inputs[i].index == i, "model input order");
        require(inputs[i].type ==
                    (sdk.uint8_input ? RKNN_TENSOR_UINT8 : RKNN_TENSOR_FLOAT32),
                "external input format");
        require(inputs[i].fmt == RKNN_TENSOR_UNDEFINED, "queried layout retained");
        require(inputs[i].pass_through == 0, "SDK conversion enabled");
        require(inputs[i].size ==
                    (i == 0 ? 3 : 2) * (sdk.uint8_input ? 1 : sizeof(float)),
                "float byte size");
        std::vector<float> values(i == 0 ? 3 : 2);
        if (sdk.uint8_input) {
            auto* bytes = static_cast<unsigned char*>(inputs[i].buf);
            for (size_t j = 0; j < values.size(); ++j)
                values[j] = bytes[j];
        } else
            std::memcpy(values.data(), inputs[i].buf, inputs[i].size);
        sdk.submitted.push_back(values);
    }
    return sdk.fail_set ? -1 : RKNN_SUCC;
}
int rknn_outputs_get(rknn_context,
                     uint32_t count,
                     rknn_output* outputs,
                     rknn_output_extend*) {
    ++sdk.gets;
    require(count == 1, "output count");
    require(outputs[0].want_float == 1 && outputs[0].index == 0 &&
                outputs[0].is_prealloc == 1,
            "float caller-owned output requested");
    if (sdk.fail_get) {
        // Failed retrieval may already have written into caller storage.
        static_cast<float*>(outputs[0].buf)[0] = 99.0f;
        return -1;
    }
    require(outputs[0].buf != nullptr && outputs[0].size == 3 * sizeof(float),
            "preallocated output capacity");
    const float values[] = {0.25f, 0.5f, 0.75f};
    std::memcpy(outputs[0].buf, values, sizeof(values));
    outputs[0].size = sdk.bad_output_size ? 4 : 3 * sizeof(float);
    return RKNN_SUCC;
}
int rknn_outputs_release(rknn_context, uint32_t count, rknn_output* outputs) {
    ++sdk.releases;
    require(count == 1, "release output count");
    require(outputs[0].is_prealloc == 1, "release must not free caller memory");
    outputs[0].buf = nullptr;
    return sdk.fail_release ? -1 : RKNN_SUCC;
}
rknn_tensor_mem* rknn_create_mem2(rknn_context, uint64_t size, uint64_t flags) {
    require(flags == RKNN_FLAG_MEMORY_CACHEABLE, "cacheable native allocation");
    auto* m = new rknn_tensor_mem{};
    m->size = size;
    m->virt_addr = new unsigned short[size / 2];
    return m;
}
int rknn_destroy_mem(rknn_context, rknn_tensor_mem* m) {
    ++sdk.mem_destroys;
    delete[] static_cast<unsigned short*>(m->virt_addr);
    delete m;
    return 0;
}
int rknn_set_io_mem(rknn_context, rknn_tensor_mem*, rknn_tensor_attr* a) {
    require(a->pass_through == 1, "native bypass explicit");
    return sdk.fail_bind ? -1 : 0;
}
int rknn_mem_sync(rknn_context, rknn_tensor_mem* m, rknn_mem_sync_mode mode) {
    require(mode == RKNN_MEMORY_SYNC_TO_DEVICE, "flush input before run");
    ++sdk.syncs;
    auto* p = static_cast<unsigned short*>(m->virt_addr);
    sdk.native_values.assign(p, p + m->size / 2);
    return sdk.fail_sync ? -1 : 0;
}
int rknn_run(rknn_context, rknn_run_extend*) {
    ++sdk.runs;
    return sdk.fail_run ? -1 : RKNN_SUCC;
}
}
int main(int argc, char** argv) {
    try {
        require(argc == 2, "model fixture argument required");
        {
            rknn::RknnBackend implementation(argv[1]);
            rtctrl::inference::Backend& backend = implementation;
            const int query_count = sdk.queries;
            require(backend.input_spec(0).byte_size() == 3 * sizeof(float),
                    "first spec");
            require(backend.input_spec(1).byte_size() == 2 * sizeof(float),
                    "second spec");
            require(backend.input_spec(0).type ==
                        rknn::RknnBackend::TensorType::Float32,
                    "public type describes submitted buffer");
            require(sdk.queries == query_count, "getter uses cached description");
            float first[] = {1, 2, 3};
            float second[] = {4, 5};
            auto unreadable = [&] {
                bool rejected = false;
                try {
                    (void)backend.output_data(0);
                } catch (const std::logic_error&) {
                    rejected = true;
                }
                require(rejected, "stale or absent output rejected");
            };
            require(backend.output_count() == 1 &&
                        backend.output_spec(0).byte_size() == 12,
                    "cached output metadata");
            unreadable();
            require(!backend.run(), "empty run rejected");
            require(!backend.prepare_input_data(nullptr, sizeof(first), 0),
                    "null rejected");
            require(!backend.prepare_input_data(first, sizeof(first) - 1, 0),
                    "wrong size rejected");
            require(!backend.prepare_input_data(first, sizeof(first), 2),
                    "bad index rejected");
            require(sdk.sets == 0, "prepare never submits");
            require(backend.prepare_input_data(second, sizeof(second), 1),
                    "prepare second first");
            require(!backend.run(), "partial inputs rejected");
            require(backend.prepare_input_data(first, sizeof(first), 0),
                    "prepare first");
            first[0] = 99;
            require(backend.run(), "complete batch runs");
            require(sdk.submitted[0][0] == 1 && sdk.submitted[1][0] == 4,
                    "copy owns data");
            require(sdk.sets == 1 && sdk.runs == 1, "one set and run per batch");
            require(backend.output_data(0) ==
                        std::vector<float>({0.25f, 0.5f, 0.75f}),
                    "caller-owned outputs survive release");
            const float* output_storage = backend.output_data(0).data();
            require(sdk.gets == 1 && sdk.releases == 1, "successful get released");
            require(!backend.run(), "repeated run needs new batch");
            unreadable();

            auto fill = [&] {
                require(backend.prepare_input_data(first, sizeof(first), 0),
                        "refill first");
                require(backend.prepare_input_data(second, sizeof(second), 1),
                        "refill second");
            };
            fill();
            sdk.fail_set = true;
            require(!backend.run(), "SDK set failure propagated");
            const int failed_sets = sdk.sets;
            sdk.fail_set = false;
            require(!backend.run() && sdk.sets == failed_sets,
                    "set failure consumes readiness");
            fill();
            sdk.fail_run = true;
            require(!backend.run(), "SDK run failure propagated");
            sdk.fail_run = false;
            const int failed_runs = sdk.runs;
            require(!backend.run() && sdk.runs == failed_runs,
                    "run failure consumes readiness");

            fill();
            sdk.fail_get = true;
            const int releases_before = sdk.releases;
            require(!backend.run(), "get failure propagated");
            require(sdk.releases == releases_before,
                    "failed get transfers no outputs");
            unreadable();
            sdk.fail_get = false;
            fill();
            sdk.bad_output_size = true;
            require(!backend.run(), "output size mismatch rejected");
            require(sdk.releases == releases_before + 1,
                    "mismatched output released");
            unreadable();
            sdk.bad_output_size = false;
            fill();
            sdk.fail_release = true;
            require(!backend.run(), "release failure propagated");
            unreadable();
            sdk.fail_release = false;
            fill();
            auto view = backend.get_input_buffer(0);
            require(view.size_bytes == sizeof(first), "writable view capacity");
            std::memcpy(view.data, first, sizeof(first));
            require(!backend.run(), "acquiring view invalidates readiness");
            require(backend.commit_input(0), "explicit commit");
            require(!backend.commit_input(2), "invalid commit index");
            require(backend.run(), "committed view and preserved other input run");
            require(backend.output_data(0).data() == output_storage,
                    "output allocation survives failures and later reuse");
            require(backend.output_data(0)[0] == 0.25f,
                    "successful retrieval replaces partial failed output");
        }
        require(sdk.destroys == 1, "normal destruction");
        sdk.fail_query = true;
        bool threw = false;
        try {
            rknn::RknnBackend implementation(argv[1]);
            rtctrl::inference::Backend& backend = implementation;
        } catch (const std::exception&) {
            threw = true;
        }
        require(threw, "failed construction reports error");
        require(sdk.destroys == 2, "failed construction releases context");
        sdk.fail_query = false;
        for (const auto bad : {FakeSdk::BadAttr::Type,
                               FakeSdk::BadAttr::Rank,
                               FakeSdk::BadAttr::ZeroDim,
                               FakeSdk::BadAttr::Overflow,
                               FakeSdk::BadAttr::ElementCount}) {
            sdk.bad_attr = bad;
            const int before = sdk.destroys;
            bool rejected = false;
            try {
                rknn::RknnBackend implementation(argv[1]);
                rtctrl::inference::Backend& backend = implementation;
            } catch (const std::exception&) {
                rejected = true;
            }
            require(rejected, "invalid model attribute rejected");
            require(sdk.destroys == before + 1,
                    "invalid attribute releases context");
        }
        sdk.bad_attr = FakeSdk::BadAttr::None;
        for (int scenario = 0; scenario < 2; ++scenario) {
            sdk.bad_output_shape = scenario == 0;
            sdk.zero_outputs = scenario == 1;
            const int before = sdk.destroys;
            bool rejected = false;
            try {
                rknn::RknnBackend backend(argv[1]);
            } catch (const std::exception&) {
                rejected = true;
            }
            require(rejected && sdk.destroys == before + 1,
                    "output contract rollback");
        }
        sdk.bad_output_shape = false;
        sdk.zero_outputs = false;
        sdk.float16_input = true;
        {
            rknn::RknnBackend backend(argv[1]);
            require(backend.input_spec(0).type ==
                        rknn::RknnBackend::TensorType::Float32,
                    "float16 native model accepts external float32");
        }
        sdk.uint8_input = true;
        {
            rknn::RknnBackend backend(argv[1], rknn::RknnBackend::TensorType::UInt8);
            require(backend.input_spec(0).byte_size() == 3, "uint8 byte size");
            auto view = backend.get_input_buffer(0);
            require(view.type == rknn::RknnBackend::TensorType::UInt8 &&
                        view.size_bytes == 3,
                    "uint8 view");
            unsigned char a[] = {0, 127, 255}, b[] = {4, 5};
            std::memcpy(view.data, a, sizeof(a));
            require(backend.commit_input(0), "uint8 commit");
            require(!backend.run(), "uint8 partial batch");
            require(!backend.prepare_input_data(b, 1, 1), "uint8 wrong size");
            require(backend.prepare_input_data(b, sizeof(b), 1) && backend.run(),
                    "uint8 full batch");
            require(sdk.submitted[0] == std::vector<float>({0, 127, 255}),
                    "uint8 values preserved");
        }
        bool bad_type = false;
        try {
            rknn::RknnBackend backend(argv[1], rknn::RknnBackend::TensorType::Int8);
        } catch (const std::invalid_argument&) {
            bad_type = true;
        }
        require(bad_type, "unsupported external type rejected");
        sdk.native = true;
        const rknn::NativeInputNormalization norm{{1, 2, 3}, {1, 2, 4}};
        const int before_mem = sdk.mem_destroys;
        {
            rknn::RknnBackend backend(argv[1], norm);
            unsigned char pixels[] = {1, 4, 7, 3, 6, 11};
            require(backend.prepare_input_data(pixels, 6, 0), "native prepare");
            int sets = sdk.sets;
            require(backend.run(), "native run");
            require(sdk.sets == sets, "native bypasses inputs_set");
            require(sdk.native_values ==
                        std::vector<unsigned short>(
                            {0, 0x3c00, 0x3c00, 0x4000, 0x4000, 0x4000}),
                    "normalized half pixels");
            sdk.fail_sync = true;
            require(backend.prepare_input_data(pixels, 6, 0), "refill native");
            int runs = sdk.runs;
            require(!backend.run() && sdk.runs == runs, "sync failure blocks run");
            bool absent = false;
            try {
                backend.output_data(0);
            } catch (const std::logic_error&) {
                absent = true;
            }
            require(absent, "sync failure invalidates outputs");
            sdk.fail_sync = false;
        }
        require(sdk.mem_destroys == before_mem + 1, "native cleanup");
        for (int scenario = 0; scenario < 3; ++scenario) {
            sdk.bad_stride = scenario == 0;
            sdk.fail_bind = scenario == 1;
            auto n = norm;
            if (scenario == 2)
                n.std[0] = 0;
            bool rejected = false;
            int before = sdk.mem_destroys;
            try {
                rknn::RknnBackend backend(argv[1], n);
            } catch (const std::exception&) {
                rejected = true;
            }
            require(rejected, "bad native setup rejected");
            require(sdk.mem_destroys == before + (scenario == 1),
                    "native setup cleanup");
        }
        sdk.bad_stride = false;
        sdk.fail_bind = false;
        std::cout << "RKNN host contract tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
