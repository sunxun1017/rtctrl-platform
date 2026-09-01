#pragma once

#include "rtctrl/control/controller.hpp"

#include <array>

namespace rtctrl::control {

struct JointPdConfig {
  std::array<double, model::kJointCount> kp{40.0, 40.0, 40.0, 40.0, 40.0, 40.0};
  std::array<double, model::kJointCount> kd{2.0, 2.0, 2.0, 2.0, 2.0, 2.0};
  double max_effort{20.0};
};

class JointPd final : public IController {
public:
  explicit JointPd(JointPdConfig config = {}) noexcept : config_(config) {}
  void reset(const model::SensorFrame& state) noexcept override;
  bool update(const model::SensorFrame& state, const ControlContext& context,
              model::CommandFrame& command) noexcept override;

private:
  JointPdConfig config_{};
  std::uint64_t command_sequence_{0};
};

}  // namespace rtctrl::control

