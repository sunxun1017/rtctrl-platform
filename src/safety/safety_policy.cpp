#include "rtctrl/safety/safety_policy.hpp"

#include <cmath>

namespace rtctrl::safety {

SafetyDecision SafetyPolicy::evaluate(const model::SensorFrame& state,
                                      const model::CommandFrame& command,
                                      std::int64_t now_ns) const noexcept {
  if (state.fault_bits != 0) {
    return SafetyDecision::HardwareFault;
  }
  if (command.mode != model::CommandMode::Position || now_ns > command.valid_until_ns) {
    return SafetyDecision::CommandExpired;
  }
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    if (!std::isfinite(state.position[i]) || !std::isfinite(state.velocity[i]) ||
        !std::isfinite(state.effort[i]) || !std::isfinite(command.target_position[i]) ||
        !std::isfinite(command.target_velocity[i]) || !std::isfinite(command.effort[i]) ||
        !std::isfinite(command.kp[i]) || !std::isfinite(command.kd[i])) {
      return SafetyDecision::InvalidNumber;
    }
    if (std::abs(state.position[i]) > limits_.max_position_abs ||
        std::abs(command.target_position[i]) > limits_.max_position_abs ||
        std::abs(state.velocity[i]) > limits_.max_velocity_abs ||
        std::abs(command.target_velocity[i]) > limits_.max_velocity_abs ||
        std::abs(state.effort[i]) > limits_.max_effort_abs ||
        std::abs(command.effort[i]) > limits_.max_effort_abs || command.kp[i] < 0.0 ||
        command.kp[i] > limits_.max_kp || command.kd[i] < 0.0 ||
        command.kd[i] > limits_.max_kd) {
      return SafetyDecision::LimitViolation;
    }
  }
  return SafetyDecision::Accept;
}

void SafetyPolicy::make_safe_command(const model::SensorFrame& state, std::int64_t now_ns,
                                     model::CommandFrame& command) const noexcept {
  command = {};
  command.created_time_ns = now_ns;
  command.valid_until_ns = now_ns + 1'000'000;
  command.mode = model::CommandMode::SafeStop;
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    command.target_position[i] = std::isfinite(state.position[i]) ? state.position[i] : 0.0;
  }
}

}  // namespace rtctrl::safety
