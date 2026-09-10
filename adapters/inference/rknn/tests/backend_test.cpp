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
    int queries = 0;
    int sets = 0;
    int runs = 0;
    int destroys = 0;
    int gets = 0;
    int releases = 0;
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
        count->n_input = 2;
        count->n_output = sdk.zero_outputs ? 0 : 1;
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
        require(inputs[i].type == RKNN_TENSOR_FLOAT32, "public float input format");
        require(inputs[i].fmt == RKNN_TENSOR_UNDEFINED, "queried layout retained");
        require(inputs[i].pass_through == 0, "SDK conversion enabled");
        require(inputs[i].size == (i == 0 ? 3 : 2) * sizeof(float),
                "float byte size");
        std::vector<float> values(inputs[i].size / sizeof(float));
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
                outputs[0].is_prealloc == 0,
            "float SDK-owned output requested");
    if (sdk.fail_get)
        return -1;
    auto* values = new float[3]{0.25f, 0.5f, 0.75f};
    outputs[0].buf = values;
    outputs[0].size = sdk.bad_output_size ? 4 : 3 * sizeof(float);
    return RKNN_SUCC;
}
int rknn_outputs_release(rknn_context, uint32_t count, rknn_output* outputs) {
    ++sdk.releases;
    require(count == 1, "release output count");
    delete[] static_cast<float*>(outputs[0].buf);
    outputs[0].buf = nullptr;
    return sdk.fail_release ? -1 : RKNN_SUCC;
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
                    "outputs copied before release");
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
        std::cout << "RKNN host contract tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
