#pragma once

#include "rtctrl/transport/byte_transport.hpp"

#include <array>
#include <cstdint>

namespace rtctrl::transport {

class PosixSerialTransport final : public IByteTransport {
public:
  static constexpr std::size_t kDevicePathCapacity = 128;

  PosixSerialTransport(const char* device, int baud_rate) noexcept;
  ~PosixSerialTransport() override;

  TransportStatus open() noexcept override;
  IoResult try_receive(std::byte* destination, std::size_t capacity) noexcept override;
  IoResult try_send(const std::byte* source, std::size_t size) noexcept override;
  void close() noexcept override;

private:
  std::array<char, kDevicePathCapacity> device_{};
  int baud_rate_{115200};
  int fd_{-1};
  bool config_valid_{false};
};

}  // namespace rtctrl::transport
