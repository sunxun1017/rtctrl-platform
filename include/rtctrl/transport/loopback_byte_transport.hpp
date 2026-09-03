#pragma once

#include "rtctrl/transport/byte_transport.hpp"

#include <array>
#include <cstddef>

namespace rtctrl::transport {

// Deterministic byte transport for codec/integration tests. It deliberately
// supports short reads to exercise UART/NearLink fragmentation behavior.
class LoopbackByteTransport final : public IByteTransport {
  public:
    static constexpr std::size_t kCapacity = 2048;

    explicit LoopbackByteTransport(std::size_t max_chunk = kCapacity) noexcept
        : max_chunk_(max_chunk == 0 ? 1 : max_chunk) {}

    TransportStatus open() noexcept override;
    IoResult try_receive(std::byte* destination, std::size_t capacity) noexcept override;
    IoResult try_send(const std::byte* source, std::size_t size) noexcept override;
    void close() noexcept override;

    bool inject(const std::byte* source, std::size_t size) noexcept;
    std::size_t drain_sent(std::byte* destination, std::size_t capacity) noexcept;

  private:
    std::array<std::byte, kCapacity> rx_{};
    std::array<std::byte, kCapacity> tx_{};
    std::size_t rx_size_{0};
    std::size_t tx_size_{0};
    std::size_t max_chunk_{kCapacity};
    bool open_{false};
};

} // namespace rtctrl::transport
