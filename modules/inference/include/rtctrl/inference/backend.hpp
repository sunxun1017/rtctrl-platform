#ifndef RTCTRL_INFERENCE_BACKEND_HPP
#define RTCTRL_INFERENCE_BACKEND_HPP

#include "rtctrl/inference/tensor.hpp"
#include <stdexcept>
#include <vector>

namespace rtctrl::inference {

// Source-level C++ interface, not a stable binary plugin ABI. One owner thread,
// synchronous execution; model management and inference are not real-time work.
class Backend {
  public:
    virtual ~Backend() = default;
    virtual std::size_t input_count() const noexcept = 0;

    // Borrows metadata until destruction/model replacement.
    // Invalid indices throw std::out_of_range.
    virtual const TensorSpec& input_spec(std::size_t index) const = 0;

    // Borrows storage until destruction/model replacement and invalidates this
    // input's prepared state. Do not free it or write during run. After commit,
    // obtain a new view before further writes. Invalid indices throw
    // std::out_of_range. Acquiring a view alone does not prepare input.
    virtual MutableTensorView get_input_buffer(std::size_t index) = 0;

    // Confirms the whole input was filled in the agreed format.
    // Invalid indices return false.
    virtual bool commit_input(std::size_t index) = 0;

    // Copies one complete input into owned storage and marks it prepared.
    // No preprocessing/conversion: source type/layout must match the spec.
    // Invalid index, null data or size mismatch returns false. Failed updates
    // of valid inputs invalidate their previous prepared state.
    virtual bool prepare_input_data(const void* data,
                                    std::size_t size_bytes,
                                    std::size_t index) = 0;

    // Optional dense Float32 outputs. Metadata is cached; data is borrowed until
    // the next run attempt or destruction. Reading before a successful run throws.
    virtual std::size_t output_count() const noexcept {
        return 0;
    }
    virtual const TensorSpec& output_spec(std::size_t) const {
        throw std::logic_error("Backend does not expose outputs");
    }
    virtual const std::vector<float>& output_data(std::size_t) const {
        throw std::logic_error("Backend does not expose outputs");
    }

    // Requires all inputs prepared. Missing inputs return false without
    // consuming readiness. Once submission is attempted, all readiness is
    // consumed, including on SDK failure. Every run attempt invalidates prior output
    // data.
    virtual bool run() = 0;
};

} // namespace rtctrl::inference
#endif
