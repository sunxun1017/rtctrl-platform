#pragma once

#include "rtctrl/hal/actuator_hal.hpp"
#include "rtctrl/ipc/shared_motor_abi.hpp"

#include <cstdint>

namespace rtctrl::hal {

struct SharedMemoryHalConfig {
  std::int64_t max_feedback_age_ns{20'000'000};
};

// Controller-side HAL for the ROS-free L0 shared-memory boundary. Mapping and
// ownership are deliberately handled by ipc::PosixSharedMemoryRegion so this
// adapter can be unit-tested against an in-memory region.
class SharedMemoryHal final : public IActuatorHal {
public:
  explicit SharedMemoryHal(ipc::SharedMotorRegion& region,
                           SharedMemoryHalConfig config = {}) noexcept
      : region_(region), config_(config) {}

  HalStatus open_safe(std::int64_t now_ns) noexcept override;
  HalStatus arm(std::int64_t now_ns) noexcept override;
  HalStatus read(std::int64_t now_ns, model::SensorFrame& output) noexcept override;
  HalStatus write(std::int64_t now_ns,
                  const model::CommandFrame& input) noexcept override;
  void emergency_stop(std::int64_t now_ns) noexcept override;
  void close() noexcept override;

private:
  ipc::SharedMotorRegion& region_;
  SharedMemoryHalConfig config_{};
  ipc::FeedbackSnapshot last_feedback_{};
  bool opened_{false};
  bool armed_{false};
  bool have_feedback_{false};
};

}  // namespace rtctrl::hal
