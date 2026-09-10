#pragma once

#include "rtctrl/transport/byte_transport.hpp"

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::transport {

constexpr std::size_t kCanFdMaxPayload = 64;
constexpr std::uint32_t kCanStandardIdMask = 0x7ffU;
constexpr std::uint32_t kCanExtendedIdMask = 0x1fffffffU;

// Frame-level CAN/CAN-FD contract. It deliberately contains no motor-specific
// object dictionary, arbitration IDs, scaling, or command semantics.
struct CanFrame {
    std::uint32_t id{0};
    std::array<std::byte, kCanFdMaxPayload> data{};
    std::uint8_t size{0};
    bool fd{true};
    bool extended{false};
    bool bit_rate_switch{false};
    bool error_state_indicator{false};
    bool remote_request{false};
    bool error_frame{false};
    std::int64_t timestamp_ns{0};
};

struct CanFilter {
    std::uint32_t id{0};
    std::uint32_t mask{0};
    bool extended{false};
};

struct CanIoResult {
    TransportStatus status{TransportStatus::Error};
    int native_error{0};
};

class ICanTransport {
  public:
    virtual ~ICanTransport() = default;

    virtual TransportStatus open() noexcept = 0;
    // Calls are bounded, non-blocking, and allocation-free after open().
    virtual CanIoResult try_receive(CanFrame& output) noexcept = 0;
    virtual CanIoResult try_send(const CanFrame& input) noexcept = 0;
    virtual void close() noexcept = 0;
};

inline bool valid_can_frame(const CanFrame& frame, bool for_transmit) noexcept {
    const auto id_mask = frame.extended ? kCanExtendedIdMask : kCanStandardIdMask;
    if (frame.id > id_mask || frame.size > kCanFdMaxPayload) {
        return false;
    }
    if (!frame.fd && frame.size > 8U) {
        return false;
    }
    if (!frame.fd && (frame.bit_rate_switch || frame.error_state_indicator)) {
        return false;
    }
    if (frame.fd && frame.remote_request) {
        return false;
    }
    if (for_transmit && frame.error_frame) {
        return false;
    }
    return true;
}

} // namespace rtctrl::transport
