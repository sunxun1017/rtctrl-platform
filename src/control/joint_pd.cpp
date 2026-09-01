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
    if (!std::isfinite(target) || !std::isfinite(config_.kp[i]) ||
        !std::isfinite(config_.kd[i]) || !std::isfinite(state.position[i]) ||
        !std::isfinite(state.velocity[i])) {
      return false;
    }
    command.target_position[i] = target;
    command.target_velocity[i] = 0.0;
    command.effort[i] = 0.0;
    command.kp[i] = config_.kp[i];
    command.kd[i] = config_.kd[i];
  }
  return true;
}

}  // namespace rtctrl::control
