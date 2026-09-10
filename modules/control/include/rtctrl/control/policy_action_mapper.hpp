#pragma once

#include "rtctrl/model/frames.hpp"

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::control {

struct PolicyActionConfig {
    PolicyActionConfig() noexcept;

    std::size_t action_count{0};
    std::array<int, model::kJointCount> logical_joint{};
    std::array<double, model::kJointCount> default_position{};
    std::array<double, model::kJointCount> action_scale{};
    std::array<double, model::kJointCount> action_lower{};
    std::array<double, model::kJointCount> action_upper{};
    std::array<double, model::kJointCount> delta_scale{};
    std::array<double, model::kJointCount> kp{};
    std::array<double, model::kJointCount> kd{};
    std::array<double, model::kJointCount> joint_lower{};
    std::array<double, model::kJointCount> joint_upper{};
};

// Converts a base policy action and an optional learned delta-action residual
// into the stable logical-joint command contract. No ONNX/ROS dependency and
// no allocation: inference backends remain leaf adapters.
class PolicyActionMapper {
  public:
    explicit PolicyActionMapper(PolicyActionConfig config) noexcept
        : config_(config), valid_(validate(config_)) {}

    bool valid() const noexcept {
        return valid_;
    }
    bool map(const float* base_action, const float* delta_action, std::int64_t now_ns,
             std::int64_t validity_ns, model::CommandFrame& output) noexcept;

  private:
    static bool validate(const PolicyActionConfig& config) noexcept;

    PolicyActionConfig config_{};
    bool valid_{false};
    std::uint64_t sequence_{0};
};

} // namespace rtctrl::control
