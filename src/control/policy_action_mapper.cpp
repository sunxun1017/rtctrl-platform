#include "rtctrl/control/policy_action_mapper.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace rtctrl::control {

PolicyActionConfig::PolicyActionConfig() noexcept {
  logical_joint.fill(-1);
  action_scale.fill(1.0);
  action_lower.fill(-1.0);
  action_upper.fill(1.0);
  delta_scale.fill(0.0);
  kp.fill(40.0);
  kd.fill(2.0);
  joint_lower.fill(-3.2);
  joint_upper.fill(3.2);
}

bool PolicyActionMapper::validate(const PolicyActionConfig& config) noexcept {
  if (config.action_count == 0 || config.action_count > model::kJointCount) {
    return false;
  }
  std::array<bool, model::kJointCount> occupied{};
  for (std::size_t i = 0; i < config.action_count; ++i) {
    const int target = config.logical_joint[i];
    if (target < 0 || static_cast<std::size_t>(target) >= model::kJointCount ||
        occupied[static_cast<std::size_t>(target)] ||
        !std::isfinite(config.action_scale[i]) ||
        !std::isfinite(config.delta_scale[i]) ||
        !std::isfinite(config.action_lower[i]) ||
        !std::isfinite(config.action_upper[i]) ||
        config.action_lower[i] > config.action_upper[i]) {
      return false;
    }
    occupied[static_cast<std::size_t>(target)] = true;
  }
  for (std::size_t joint = 0; joint < model::kJointCount; ++joint) {
    if (!std::isfinite(config.default_position[joint]) ||
        !std::isfinite(config.kp[joint]) || !std::isfinite(config.kd[joint]) ||
        config.kp[joint] < 0.0 || config.kd[joint] < 0.0 ||
        !std::isfinite(config.joint_lower[joint]) ||
        !std::isfinite(config.joint_upper[joint]) ||
        config.joint_lower[joint] > config.joint_upper[joint]) {
      return false;
    }
  }
  return true;
}

bool PolicyActionMapper::map(const float* base_action, const float* delta_action,
                             std::int64_t now_ns, std::int64_t validity_ns,
                             model::CommandFrame& output) noexcept {
  if (!valid_ || base_action == nullptr || now_ns < 0 || validity_ns <= 0 ||
      now_ns > std::numeric_limits<std::int64_t>::max() - validity_ns) {
    return false;
  }
  output = {};
  output.sequence = ++sequence_;
  output.created_time_ns = now_ns;
  output.valid_until_ns = now_ns + validity_ns;
  output.mode = model::CommandMode::Position;
  for (std::size_t joint = 0; joint < model::kJointCount; ++joint) {
    output.target_position[joint] = std::clamp(
        config_.default_position[joint], config_.joint_lower[joint],
        config_.joint_upper[joint]);
    output.kp[joint] = config_.kp[joint];
    output.kd[joint] = config_.kd[joint];
  }

  for (std::size_t i = 0; i < config_.action_count; ++i) {
    const double base = static_cast<double>(base_action[i]);
    const double delta = delta_action == nullptr
                             ? 0.0
                             : static_cast<double>(delta_action[i]);
    if (!std::isfinite(base) || !std::isfinite(delta)) {
      return false;
    }
    const double residual = std::clamp(
        base + config_.delta_scale[i] * delta, config_.action_lower[i],
        config_.action_upper[i]);
    const auto joint = static_cast<std::size_t>(config_.logical_joint[i]);
    const double target = config_.default_position[joint] +
                          residual * config_.action_scale[i];
    output.target_position[joint] =
        std::clamp(target, config_.joint_lower[joint], config_.joint_upper[joint]);
  }
  return true;
}

}  // namespace rtctrl::control
