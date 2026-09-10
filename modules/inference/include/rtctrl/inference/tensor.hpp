#ifndef RTCTRL_INFERENCE_TENSOR_HPP
#define RTCTRL_INFERENCE_TENSOR_HPP

#include <cstddef>
#include <cstdint>
#include <vector>

namespace rtctrl::inference {

enum class TensorType { UInt8, Int8, Float32 };
enum class TensorLayout { NCHW, NHWC, Undefined };

// Describes the submitted, densely packed representation, not SDK-native storage.
struct TensorSpec {
    std::vector<std::uint32_t> shape;
    TensorType type = TensorType::Float32;
    TensorLayout layout = TensorLayout::Undefined;

    // Empty shape means one scalar. Zero dimensions/unknown types throw
    // std::invalid_argument; unrepresentable sizes throw std::overflow_error.
    std::size_t byte_size() const;
};

// Non-owning writable memory; type must agree with input_spec(index).
struct MutableTensorView {
    TensorType type;
    void* data;
    std::size_t size_bytes;
};

} // namespace rtctrl::inference
#endif
