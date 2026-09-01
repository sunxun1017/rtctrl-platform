#include "rtctrl/control/joint_pd.hpp"

#include <algorithm>
#include <cmath>

namespace rtctrl::control {

void JointPd::reset(const model::SensorFrame&) noexcept { command_sequence_ = 0; }

bool JointPd::update(const model::SensorFrame& state, const ControlContext& context,
                     model::CommandFrame& command) noexcept {
  command = {};
  command.sequence = ++command_sequence_;
  command.created_time_ns = context.now_ns;
  command.valid_until_ns = context.now_ns + context.command_validity_ns;
  command.mode = model::CommandMode::Position;

  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    const double target = context.target.position[i];
    const double effort = config_.kp[i] * (target - state.position[i]) -
                          config_.kd[i] * state.velocity[i];
    if (!std::isfinite(effort)) {
      return false;
    }
    command.target_position[i] = target;
    command.target_velocity[i] = 0.0;
    command.effort[i] = std::clamp(effort, -config_.max_effort, config_.max_effort);
  }
  return true;
}

}  // namespace rtctrl::control

