#pragma once

#include "rtctrl/model/frames.hpp"

namespace rtctrl::bridge {

class ITargetIngress {
  public:
    virtual ~ITargetIngress() = default;
    virtual bool try_submit(const model::ControlTarget& target) noexcept = 0;
};

class IStateSnapshot {
  public:
    virtual ~IStateSnapshot() = default;
    virtual bool try_read_latest(model::SensorFrame& state) const noexcept = 0;
};

class ILifecycleControl {
  public:
    virtual ~ILifecycleControl() = default;
    virtual bool request_arm() noexcept = 0;
    virtual void request_disarm() noexcept = 0;
    virtual void request_stop() noexcept = 0;
};

} // namespace rtctrl::bridge
