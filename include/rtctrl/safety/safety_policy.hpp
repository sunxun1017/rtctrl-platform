#pragma once

#include "rtctrl/model/frames.hpp"

#include <cstdint>

namespace rtctrl::safety {

enum class SafetyDecision : std::uint8_t {
  Accept = 0,
  CommandExpired,
  InvalidNumber,
  LimitViolation,
  HardwareFault
};

struct SafetyLimits {
  double max_position_abs{3.2};
  double max_velocity_abs{8.0};
  double max_effort_abs{25.0};
};

class SafetyPolicy {
public:
  explicit SafetyPolicy(SafetyLimits limits = {}) noexcept : limits_(limits) {}
  SafetyDecision evaluate(const model::SensorFrame& state, const model::CommandFrame& command,
                          std::int64_t now_ns) const noexcept;
  void make_safe_command(const model::SensorFrame& state, std::int64_t now_ns,
                         model::CommandFrame& command) const noexcept;

private:
  SafetyLimits limits_{};
};

}  // namespace rtctrl::safety

