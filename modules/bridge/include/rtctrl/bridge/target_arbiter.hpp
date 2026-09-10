#pragma once

#include "rtctrl/bridge/command_source.hpp"
#include "rtctrl/runtime/runtime_ports.hpp"
#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::bridge {

// Single non-RT owner calls bind/poll. Sources must return promptly; network
// workers hand off through their own bounded queues. Larger priority wins;
// ties use the lower slot. Source sessions are reset by rebuilding this object.
class TargetArbiter {
  public:
    static constexpr std::size_t kMaxSources = 4;
    explicit TargetArbiter(runtime::ITargetIngress& ingress,
                           std::int64_t lease_ns = 100'000'000) noexcept
        : ingress_(ingress)
        , lease_ns_(lease_ns) {}
    bool bind(std::size_t slot, ICommandSource& source, unsigned priority) noexcept;
    bool poll(std::int64_t now_ns) noexcept;
    std::uint64_t rejected() const noexcept {
        return rejected_;
    }
    std::uint64_t backpressure() const noexcept {
        return backpressure_;
    }

  private:
    struct Source {
        ICommandSource* input{nullptr};
        unsigned priority{0};
        model::ControlTarget latest{};
        std::uint64_t sequence{0};
        bool valid{false};
    };
    runtime::ITargetIngress& ingress_;
    std::int64_t lease_ns_;
    std::array<Source, kMaxSources> sources_{};
    std::size_t published_slot_{kMaxSources};
    std::uint64_t published_sequence_{0};
    std::uint64_t output_sequence_{0};
    std::uint64_t rejected_{0};
    std::uint64_t backpressure_{0};
    bool started_{false};
};

} // namespace rtctrl::bridge
