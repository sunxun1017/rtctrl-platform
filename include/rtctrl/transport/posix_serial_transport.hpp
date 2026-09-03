#pragma once

#include "rtctrl/transport/byte_transport.hpp"

#include <array>
#include <cstdint>

namespace rtctrl::transport {

struct PosixSerialOptions {
  const char* device{nullptr};
  int baud_rate{115200};
  // Enable only for UART controllers wired to an RS-485 transceiver whose
  // direction is controlled by the Linux serial core. U2D2 and hardware
  // auto-direction adapters must leave this false.
  bool linux_rs485{false};
  bool rts_high_while_sending{true};
  std::uint32_t delay_before_send_ms{0};
  std::uint32_t delay_after_send_ms{0};
};

class PosixSerialTransport final : public IByteTransport {
public:
  static constexpr std::size_t kDevicePathCapacity = 128;

  PosixSerialTransport(const char* device, int baud_rate) noexcept;
  explicit PosixSerialTransport(const PosixSerialOptions& options) noexcept;
  ~PosixSerialTransport() override;

  TransportStatus open() noexcept override;
  IoResult try_receive(std::byte* destination, std::size_t capacity) noexcept override;
  IoResult try_send(const std::byte* source, std::size_t size) noexcept override;
  void close() noexcept override;

private:
  std::array<char, kDevicePathCapacity> device_{};
  int baud_rate_{115200};
  int fd_{-1};
  bool linux_rs485_{false};
  bool rts_high_while_sending_{true};
  std::uint32_t delay_before_send_ms_{0};
  std::uint32_t delay_after_send_ms_{0};
  bool config_valid_{false};
};

}  // namespace rtctrl::transport
