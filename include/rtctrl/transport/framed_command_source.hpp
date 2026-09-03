#pragma once

#include "rtctrl/protocol/target_codec.hpp"
#include "rtctrl/transport/byte_transport.hpp"
#include "rtctrl/transport/command_source.hpp"

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::transport {

struct FramedSourcePolicy {
    std::uint32_t max_lease_us{100'000};
    std::size_t max_frames_per_poll{4};
};

struct FramedSourceMetrics {
    std::uint64_t frames_ok{0};
    std::uint64_t framing_errors{0};
    std::uint64_t transport_errors{0};
    std::uint64_t expired_frames{0};
    std::uint64_t replayed_frames{0};
    std::uint64_t session_errors{0};
    std::uint64_t sender_time_regressions{0};
    std::uint64_t bytes_discarded{0};
};

class FramedCommandSource final : public ICommandSource {
  public:
    static constexpr std::size_t kRxCapacity = 512;

    FramedCommandSource(IByteTransport& transport, protocol::ITargetCodec& codec,
                        FramedSourcePolicy policy = {}) noexcept
        : transport_(transport), codec_(codec), policy_(policy) {}

    TransportStatus open() noexcept;
    void close() noexcept;
    void reset_link_session() noexcept;
    bool poll(std::int64_t now_ns, model::ControlTarget& target) noexcept override;
    const FramedSourceMetrics& metrics() const noexcept {
        return metrics_;
    }

  private:
    void consume(std::size_t count) noexcept;

    IByteTransport& transport_;
    protocol::ITargetCodec& codec_;
    FramedSourcePolicy policy_{};
    FramedSourceMetrics metrics_{};
    std::array<std::byte, kRxCapacity> rx_{};
    std::size_t rx_size_{0};
    std::uint32_t session_id_{0};
    std::uint64_t last_sequence_{0};
    std::uint64_t last_sender_time_ns_{0};
    bool open_{false};
};

} // namespace rtctrl::transport
