#pragma once

#include "rtctrl/model/frames.hpp"

#include <cstdint>

namespace rtctrl::hal {

enum class HalStatus : std::uint8_t { Ok = 0, NotReady, IoError };

class IActuatorHal {
  public:
    virtual ~IActuatorHal() = default;
    // open_safe() may initialize resources but must never energize an actuator.
    // All real-time calls are bounded, non-blocking and allocation-free.
    virtual HalStatus open_safe(std::int64_t now_ns) noexcept = 0;
    // The runtime performs one successful read() before arm(), allowing adapters
    // to seed a jump-free hold command from measured state.
    virtual HalStatus arm(std::int64_t now_ns) noexcept = 0;
    virtual HalStatus read(std::int64_t now_ns, model::SensorFrame& output) noexcept = 0;
    virtual HalStatus write(std::int64_t now_ns, const model::CommandFrame& input) noexcept = 0;
    // emergency_stop() must be idempotent and is the only emergency hardware exit.
    virtual void emergency_stop(std::int64_t now_ns) noexcept = 0;
    virtual void close() noexcept = 0;
};

} // namespace rtctrl::hal
