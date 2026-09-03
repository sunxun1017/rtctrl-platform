#pragma once

#include "rtctrl/transport/can_transport.hpp"

#include <array>
#include <cstddef>

namespace rtctrl::transport {

struct SocketCanFdConfig {
    bool loopback{true};
    bool receive_own_messages{false};
    bool receive_error_frames{true};
    bool receive_timestamps{true};
};

// Linux SocketCAN RAW adapter supporting both Classical CAN and CAN-FD on the
// same socket. Link bitrate/data-bitrate and interface state remain system
// configuration, normally managed by iproute2 or systemd-networkd.
class SocketCanFdTransport final : public ICanTransport {
  public:
    static constexpr std::size_t kInterfaceNameCapacity = 16;
    static constexpr std::size_t kMaxFilters = 32;

    explicit SocketCanFdTransport(const char* interface_name,
                                  SocketCanFdConfig config = {}) noexcept;
    ~SocketCanFdTransport() override;

    // Must be called before open(). An empty list restores receive-all behavior.
    bool set_filters(const CanFilter* filters, std::size_t count) noexcept;

    TransportStatus open() noexcept override;
    CanIoResult try_receive(CanFrame& output) noexcept override;
    CanIoResult try_send(const CanFrame& input) noexcept override;
    void close() noexcept override;

    int native_handle() const noexcept {
        return fd_;
    }
    int last_error() const noexcept {
        return last_error_;
    }

  private:
    std::array<char, kInterfaceNameCapacity> interface_name_{};
    SocketCanFdConfig config_{};
    std::array<CanFilter, kMaxFilters> filters_{};
    std::size_t filter_count_{0};
    int fd_{-1};
    int last_error_{0};
    bool config_valid_{false};
};

} // namespace rtctrl::transport
