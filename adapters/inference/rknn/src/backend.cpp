#include "rtctrl/adapters/rknn/backend.hpp"

#include <algorithm>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>

namespace rknn {
namespace {
std::vector<unsigned char> load_model(const char* path) {
    if (path == nullptr || *path == '\0') {
        throw std::invalid_argument("RKNN model path is empty");
    }
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        throw std::runtime_error("Cannot open RKNN model");
    }
    const auto length = file.tellg();
    if (length <= 0 || static_cast<std::uintmax_t>(length) >
                           std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("Invalid RKNN model size");
    }
    std::vector<unsigned char> bytes(static_cast<std::size_t>(length));
    file.seekg(0);
    if (!file.read(reinterpret_cast<char*>(bytes.data()),
                   static_cast<std::streamsize>(bytes.size()))) {
        throw std::runtime_error("Cannot read RKNN model");
    }
    return bytes;
}
} // namespace

RknnBackend::RknnBackend(const char* model_path, TensorType input_type)
    : model_(load_model(model_path)) {
    static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559,
                  "RKNN Float32 requires IEEE 754 32-bit float");
    if (input_type != TensorType::Float32 && input_type != TensorType::UInt8)
        throw std::invalid_argument("Unsupported external RKNN input type");
    try {
        if (rknn_init(&ctx_,
                      model_.data(),
                      static_cast<std::uint32_t>(model_.size()),
                      0,
                      nullptr) != RKNN_SUCC) {
            throw std::runtime_error("rknn_init failed");
        }
        rknn_input_output_num counts{};
        if (rknn_query(ctx_, RKNN_QUERY_IN_OUT_NUM, &counts, sizeof(counts)) !=
                RKNN_SUCC ||
            counts.n_input == 0 || counts.n_output == 0) {
            throw std::runtime_error("Cannot query RKNN input count");
        }
        input_specs_.reserve(counts.n_input);
        input_buffers_.resize(counts.n_input);
        input_bytes_.resize(counts.n_input);
        inputs_.resize(counts.n_input);
        input_ready_.assign(counts.n_input, false);
        for (std::uint32_t i = 0; i < counts.n_input; ++i) {
            rknn_tensor_attr attr{};
            attr.index = i;
            if (rknn_query(ctx_, RKNN_QUERY_INPUT_ATTR, &attr, sizeof(attr)) !=
                RKNN_SUCC) {
                throw std::runtime_error("Cannot query RKNN input attributes");
            }
            if (attr.n_dims > RKNN_MAX_DIMS ||
                (attr.type != RKNN_TENSOR_FLOAT32 &&
                 attr.type != RKNN_TENSOR_FLOAT16 &&
                 attr.type != RKNN_TENSOR_UINT8 && attr.type != RKNN_TENSOR_INT8)) {
                throw std::runtime_error("Unsupported RKNN input type or rank");
            }
            TensorSpec spec{};
            spec.type = input_type;
            spec.shape.assign(attr.dims, attr.dims + attr.n_dims);
            switch (attr.fmt) {
                case RKNN_TENSOR_NCHW:
                    spec.layout = TensorLayout::NCHW;
                    break;
                case RKNN_TENSOR_NHWC:
                    spec.layout = TensorLayout::NHWC;
                    break;
                case RKNN_TENSOR_UNDEFINED:
                    spec.layout = TensorLayout::Undefined;
                    break;
                default:
                    throw std::runtime_error("Unsupported RKNN input layout");
            }
            const auto bytes = spec.byte_size();
            if (bytes > std::numeric_limits<std::uint32_t>::max() ||
                bytes / (input_type == TensorType::Float32 ? sizeof(float) : 1) !=
                    attr.n_elems) {
                throw std::runtime_error(
                    "Inconsistent or oversized RKNN input shape");
            }
            if (input_type == TensorType::Float32)
                input_buffers_[i].resize(bytes / sizeof(float));
            else
                input_bytes_[i].resize(bytes);
            input_specs_.push_back(spec);
            auto& input = inputs_[i];
            input.index = i;
            input.type = input_type == TensorType::Float32 ? RKNN_TENSOR_FLOAT32
                                                           : RKNN_TENSOR_UINT8;
            input.fmt = attr.fmt;
            input.pass_through = 0;
            input.size = static_cast<std::uint32_t>(bytes);
            input.buf = input_type == TensorType::Float32
                            ? static_cast<void*>(input_buffers_[i].data())
                            : static_cast<void*>(input_bytes_[i].data());
        }
        output_specs_.reserve(counts.n_output);
        output_buffers_.resize(counts.n_output);
        for (std::uint32_t i = 0; i < counts.n_output; ++i) {
            rknn_tensor_attr attr{};
            attr.index = i;
            if (rknn_query(ctx_, RKNN_QUERY_OUTPUT_ATTR, &attr, sizeof(attr)) !=
                    RKNN_SUCC ||
                attr.n_dims > RKNN_MAX_DIMS) {
                throw std::runtime_error("Cannot query RKNN output attributes");
            }
            TensorSpec spec{};
            spec.shape.assign(attr.dims, attr.dims + attr.n_dims);
            switch (attr.fmt) {
                case RKNN_TENSOR_NCHW:
                    spec.layout = TensorLayout::NCHW;
                    break;
                case RKNN_TENSOR_NHWC:
                    spec.layout = TensorLayout::NHWC;
                    break;
                case RKNN_TENSOR_UNDEFINED:
                    spec.layout = TensorLayout::Undefined;
                    break;
                default:
                    throw std::runtime_error("Unsupported RKNN output layout");
            }
            const auto bytes = spec.byte_size();
            if (bytes > std::numeric_limits<std::uint32_t>::max() ||
                bytes / sizeof(float) != attr.n_elems) {
                throw std::runtime_error(
                    "Inconsistent or oversized RKNN output shape");
            }
            output_buffers_[i].resize(bytes / sizeof(float));
            output_specs_.push_back(spec);
        }
    } catch (...) {
        if (ctx_ != 0) {
            rknn_destroy(ctx_);
            ctx_ = 0;
        }
        throw;
    }
}

RknnBackend::~RknnBackend() {
    if (ctx_ != 0) {
        rknn_destroy(ctx_);
    }
}

std::size_t RknnBackend::input_count() const noexcept {
    return input_specs_.size();
}

const RknnBackend::TensorSpec& RknnBackend::input_spec(std::size_t index) const {
    return input_specs_.at(index);
}

RknnBackend::MutableTensorView RknnBackend::get_input_buffer(std::size_t index) {
    const auto& input = inputs_.at(index);
    input_ready_[index] = false;
    return {input_specs_[index].type, input.buf, input.size};
}

bool RknnBackend::commit_input(std::size_t index) {
    if (index >= input_ready_.size()) {
        return false;
    }
    input_ready_[index] = true;
    return true;
}

bool RknnBackend::prepare_input_data(const void* data,
                                     std::size_t size,
                                     std::size_t index) {
    if (index >= input_buffers_.size()) {
        return false;
    }
    input_ready_[index] = false;
    auto& input = inputs_[index];
    if (data == nullptr || size != input.size) {
        return false;
    }
    // memmove also permits a caller to commit a borrowed buffer through this API.
    std::memmove(input.buf, data, size);
    input_ready_[index] = true;
    return true;
}

std::size_t RknnBackend::output_count() const noexcept {
    return output_specs_.size();
}

const RknnBackend::TensorSpec& RknnBackend::output_spec(std::size_t index) const {
    return output_specs_.at(index);
}

const std::vector<float>& RknnBackend::output_data(std::size_t index) const {
    const auto& data = output_buffers_.at(index);
    if (!outputs_valid_)
        throw std::logic_error("No successful RKNN output available");
    return data;
}

bool RknnBackend::run() {
    outputs_valid_ = false;
    const auto failed = [&] {
        for (auto& buffer : output_buffers_)
            buffer.clear();
        return false;
    };
    if (!std::all_of(input_ready_.begin(), input_ready_.end(), [](bool ready) {
            return ready;
        })) {
        return failed();
    }
    std::fill(input_ready_.begin(), input_ready_.end(), false);
    if (rknn_inputs_set(ctx_,
                        static_cast<std::uint32_t>(inputs_.size()),
                        inputs_.data()) != RKNN_SUCC) {
        return failed();
    }
    if (rknn_run(ctx_, nullptr) != RKNN_SUCC)
        return failed();
    std::vector<rknn_output> outputs(output_specs_.size());
    for (std::size_t i = 0; i < outputs.size(); ++i) {
        // Successful runs keep this storage live. A prior failure cleared its
        // size, but retained capacity; restore the Float32 destination then.
        output_buffers_[i].resize(output_specs_[i].byte_size() / sizeof(float));
        outputs[i].index = static_cast<std::uint32_t>(i);
        outputs[i].want_float = 1;
        outputs[i].is_prealloc = 1;
        outputs[i].buf = output_buffers_[i].data();
        outputs[i].size = static_cast<std::uint32_t>(output_specs_[i].byte_size());
    }
    if (rknn_outputs_get(ctx_,
                         static_cast<std::uint32_t>(outputs.size()),
                         outputs.data(),
                         nullptr) != RKNN_SUCC)
        return failed();
    bool valid = true;
    for (std::size_t i = 0; i < outputs.size(); ++i) {
        if (outputs[i].buf != output_buffers_[i].data() ||
            outputs[i].size != output_specs_[i].byte_size()) {
            valid = false;
        }
    }
    // Release the SDK's per-get resources even for caller-owned destinations.
    // is_prealloc keeps these vectors owned by us; do not clear until release.
    const int released = rknn_outputs_release(
        ctx_, static_cast<std::uint32_t>(outputs.size()), outputs.data());
    if (!valid || released != RKNN_SUCC)
        return failed();
    outputs_valid_ = true;
    return true;
}
} // namespace rknn
