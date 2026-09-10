#pragma once

#include "rtctrl/model/frames.hpp"

namespace rtctrl::runtime {

// Exactly one producer owns an ingress. Use TargetArbiter before this port.
class ITargetIngress {
  public:
    virtual ~ITargetIngress() = default;
    virtual bool try_submit(const model::ControlTarget& target) noexcept = 0;
};

// Exactly one reader owns a snapshot port; returned data may be stale.
// Consumers must check sample_time_ns. No runtime thread waits for the reader.
class IStateSnapshot {
  public:
    virtual ~IStateSnapshot() = default;
    virtual bool try_read_latest(model::SensorFrame& state) const noexcept = 0;
};

enum class RuntimeState {
    Created,
    Starting,
    Ready,
    Armed,
    FaultLatched,
    Stopping,
    Stopped
};

class ILifecycleControl {
  public:
    virtual ~ILifecycleControl() = default;
    // Disarm is terminal for this engine instance. Re-arm requires reconstruction
    // and explicit startup authorization; there is no automatic fault recovery.
    virtual void request_disarm() noexcept = 0;
    virtual void request_stop() noexcept = 0;
    virtual RuntimeState state() const noexcept = 0;
};

} // namespace rtctrl::runtime
