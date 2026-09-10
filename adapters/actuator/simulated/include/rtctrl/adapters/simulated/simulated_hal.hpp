#pragma once

#include "rtctrl/hal/actuator_hal.hpp"

#include <cstdint>

namespace rtctrl::hal {

struct SimulatedHalConfig {
    double damping{1.5};
    double stiffness{18.0};
    std::int64_t fault_after_ns{0};
};

class SimulatedHal final : public IActuatorHal {
  public:
    explicit SimulatedHal(SimulatedHalConfig config = {}) noexcept : config_(config) {}

    HalStatus open_safe(std::int64_t now_ns) noexcept override;
    HalStatus arm(std::int64_t now_ns) noexcept override;
    HalStatus read(std::int64_t now_ns, model::SensorFrame& output) noexcept override;
    HalStatus write(std::int64_t now_ns, const model::CommandFrame& input) noexcept override;
    void emergency_stop(std::int64_t now_ns) noexcept override;
    void close() noexcept override;

  private:
    SimulatedHalConfig config_{};
    bool opened_{false};
    bool armed_{false};
    std::int64_t start_ns_{0};
    std::int64_t last_update_ns_{0};
    model::SensorFrame state_{};
    model::CommandFrame command_{};
};

} // namespace rtctrl::hal
