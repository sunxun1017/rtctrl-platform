#pragma once

#include <cstddef>
#include <cstdint>

namespace rtctrl::transport {

enum class TransportStatus : std::uint8_t { Ok, WouldBlock, Timeout, Closed, Error };

struct IoResult {
  TransportStatus status{TransportStatus::Error};
  std::size_t bytes{0};
  int native_error{0};
};

class IByteTransport {
public:
  virtual ~IByteTransport() = default;

  // Configuration is owned by the concrete adapter and applied before open().
  virtual TransportStatus open() noexcept = 0;
  // Real-time implementations must be bounded, non-blocking and allocation-free.
  virtual IoResult try_receive(std::byte* destination, std::size_t capacity) noexcept = 0;
  virtual IoResult try_send(const std::byte* source, std::size_t size) noexcept = 0;
  virtual void close() noexcept = 0;
};

}  // namespace rtctrl::transport
