#include "rtctrl/transport/loopback_byte_transport.hpp"

#include <algorithm>
#include <cstring>

namespace rtctrl::transport {

TransportStatus LoopbackByteTransport::open() noexcept {
  rx_size_ = 0;
  tx_size_ = 0;
  open_ = true;
  return TransportStatus::Ok;
}

IoResult LoopbackByteTransport::try_receive(std::byte* destination,
                                            std::size_t capacity) noexcept {
  if (!open_) {
    return {TransportStatus::Closed, 0, 0};
  }
  if (destination == nullptr || capacity == 0) {
    return {TransportStatus::Error, 0, 0};
  }
  if (rx_size_ == 0) {
    return {TransportStatus::WouldBlock, 0, 0};
  }
  const auto count = std::min({capacity, max_chunk_, rx_size_});
  std::memcpy(destination, rx_.data(), count);
  std::memmove(rx_.data(), rx_.data() + count, rx_size_ - count);
  rx_size_ -= count;
  return {TransportStatus::Ok, count, 0};
}

IoResult LoopbackByteTransport::try_send(const std::byte* source,
                                         std::size_t size) noexcept {
  if (!open_) {
    return {TransportStatus::Closed, 0, 0};
  }
  if (source == nullptr || size == 0) {
    return {TransportStatus::Error, 0, 0};
  }
  const auto available = kCapacity - tx_size_;
  if (available == 0) {
    return {TransportStatus::WouldBlock, 0, 0};
  }
  const auto count = std::min({size, max_chunk_, available});
  std::memcpy(tx_.data() + tx_size_, source, count);
  tx_size_ += count;
  return {TransportStatus::Ok, count, 0};
}

void LoopbackByteTransport::close() noexcept { open_ = false; }

bool LoopbackByteTransport::inject(const std::byte* source, std::size_t size) noexcept {
  if (!open_ || source == nullptr || size > kCapacity - rx_size_) {
    return false;
  }
  std::memcpy(rx_.data() + rx_size_, source, size);
  rx_size_ += size;
  return true;
}

std::size_t LoopbackByteTransport::drain_sent(std::byte* destination,
                                              std::size_t capacity) noexcept {
  if (destination == nullptr || capacity == 0) {
    return 0;
  }
  const auto count = std::min(capacity, tx_size_);
  std::memcpy(destination, tx_.data(), count);
  std::memmove(tx_.data(), tx_.data() + count, tx_size_ - count);
  tx_size_ -= count;
  return count;
}

}  // namespace rtctrl::transport
