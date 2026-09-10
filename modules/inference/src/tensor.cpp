#include "rtctrl/inference/tensor.hpp"

#include <limits>
#include <stdexcept>

namespace rtctrl::inference {

std::size_t TensorSpec::byte_size() const {
    std::size_t bytes = 0;
    switch (type) {
        case TensorType::UInt8:
        case TensorType::Int8:
            bytes = 1;
            break;
        case TensorType::Float32:
            bytes = 4;
            break;
        default:
            throw std::invalid_argument("Unknown tensor element type");
    }
    for (const auto dimension : shape) {
        if (dimension == 0) {
            throw std::invalid_argument("Tensor dimensions must be positive");
        }
        if (bytes > std::numeric_limits<std::size_t>::max() / dimension) {
            throw std::overflow_error("Tensor byte size exceeds size_t");
        }
        bytes *= dimension;
    }
    return bytes;
}

} // namespace rtctrl::inference
