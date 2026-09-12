#ifndef RTCTRL_ADAPTERS_RKNN_BACKEND_HPP
#define RTCTRL_ADAPTERS_RKNN_BACKEND_HPP

#include "rtctrl/inference/backend.hpp"

#include <cstddef>
#include <rknn_api.h>
#include <vector>

namespace rknn {
// Synchronous, single-owner backend. Not for the real-time control loop.
// Inputs are dense Float32 (default) or explicit UInt8 in the queried layout.
class RknnBackend final : public rtctrl::inference::Backend {
  public:
    // Throws on model loading, SDK initialization or unsupported input contracts.
    explicit RknnBackend(const char* model_path,
                         rtctrl::inference::TensorType input_type =
                             rtctrl::inference::TensorType::Float32);
    ~RknnBackend() override;
    RknnBackend(const RknnBackend&) = delete;
    RknnBackend& operator=(const RknnBackend&) = delete;
    RknnBackend(RknnBackend&&) = delete;
    RknnBackend& operator=(RknnBackend&&) = delete;

    using TensorType = rtctrl::inference::TensorType;
    using TensorLayout = rtctrl::inference::TensorLayout;
    using TensorSpec = rtctrl::inference::TensorSpec;
    using MutableTensorView = rtctrl::inference::MutableTensorView;

    std::size_t input_count() const noexcept override;
    // Cached description of the external buffer; throws on an invalid index.
    const TensorSpec& input_spec(std::size_t index) const override;

    // Borrow valid until destruction. Acquiring invalidates this input's readiness.
    // Write the queried type, then commit_input(). No writes during run().
    MutableTensorView get_input_buffer(std::size_t index) override;
    bool commit_input(std::size_t index) override;

    // Copies one dense tensor of the queried input type. No SDK calls.
    // Invalid data/size invalidates that input. Source can be released on return.
    bool prepare_input_data(const void* data,
                            std::size_t size,
                            std::size_t index) override;

    std::size_t output_count() const noexcept override;
    const TensorSpec& output_spec(std::size_t index) const override;
    // Throws logic_error unless the last run succeeded, out_of_range for bad index.
    const std::vector<float>& output_data(std::size_t index) const override;

    // Submits ALL inputs once, then executes. Every submission attempt consumes
    // readiness, including SDK failure. Missing inputs cause no SDK calls.
    // Retrieves Float32 outputs into owned storage, then releases SDK get resources.
    bool run() override;

  private:
    rknn_context ctx_{};
    // Retain model bytes until context destruction, including constructor rollback.
    std::vector<unsigned char> model_;
    std::vector<TensorSpec> input_specs_;
    std::vector<std::vector<float>> input_buffers_;
    std::vector<std::vector<unsigned char>> input_bytes_;
    std::vector<rknn_input> inputs_;
    std::vector<bool> input_ready_;
    std::vector<TensorSpec> output_specs_;
    std::vector<std::vector<float>> output_buffers_;
    bool outputs_valid_ = false;
};
} // namespace rknn
#endif
