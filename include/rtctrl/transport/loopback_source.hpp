#pragma once

#include "rtctrl/transport/command_source.hpp"

namespace rtctrl::transport {

class LoopbackSource final : public ICommandSource {
  public:
    explicit LoopbackSource(double amplitude_rad = 0.35, double frequency_hz = 0.2) noexcept
        : amplitude_rad_(amplitude_rad), frequency_hz_(frequency_hz) {}
    bool poll(std::int64_t now_ns, model::ControlTarget& target) noexcept override;

  private:
    double amplitude_rad_;
    double frequency_hz_;
    std::int64_t start_ns_{0};
    std::uint64_t sequence_{0};
};

} // namespace rtctrl::transport
