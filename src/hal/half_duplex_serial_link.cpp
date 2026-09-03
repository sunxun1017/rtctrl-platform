#include "rtctrl/hal/half_duplex_serial_link.hpp"

#include <cstring>

namespace rtctrl::hal {

ActuatorLinkStatus HalfDuplexSerialLink::map_status(
    transport::TransportStatus status) noexcept {
  switch (status) {
    case transport::TransportStatus::Ok: return ActuatorLinkStatus::Ok;
    case transport::TransportStatus::WouldBlock:
    case transport::TransportStatus::Timeout:
      return ActuatorLinkStatus::WouldBlock;
    case transport::TransportStatus::Closed: return ActuatorLinkStatus::Closed;
    case transport::TransportStatus::Error: return ActuatorLinkStatus::Error;
  }
  return ActuatorLinkStatus::Error;
}

ActuatorLinkStatus HalfDuplexSerialLink::open() noexcept {
  if (open_) {
    return ActuatorLinkStatus::Error;
  }
  const auto status = map_status(transport_.open());
  if (status == ActuatorLinkStatus::Ok) {
    open_ = true;
    transmit_size_ = 0;
    transmit_offset_ = 0;
  }
  return status;
}

ActuatorLinkStatus HalfDuplexSerialLink::flush_transmit() noexcept {
  if (transmit_offset_ == transmit_size_) {
    transmit_offset_ = 0;
    transmit_size_ = 0;
    return ActuatorLinkStatus::Ok;
  }
  const auto result = transport_.try_send(
      transmit_buffer_.data() + transmit_offset_,
      transmit_size_ - transmit_offset_);
  if (result.status == transport::TransportStatus::Ok) {
    if (result.bytes == 0U ||
        result.bytes > transmit_size_ - transmit_offset_) {
      return ActuatorLinkStatus::Error;
    }
    transmit_offset_ += result.bytes;
    if (transmit_offset_ == transmit_size_) {
      transmit_offset_ = 0;
      transmit_size_ = 0;
      return ActuatorLinkStatus::Ok;
    }
    return ActuatorLinkStatus::WouldBlock;
  }
  return map_status(result.status);
}

ActuatorLinkStatus HalfDuplexSerialLink::receive(
    std::int64_t now_ns, ActuatorPacketBatch& packets) noexcept {
  if (!open_) {
    return ActuatorLinkStatus::Closed;
  }
  if (transmit_size_ != 0U) {
    const auto flush_status = flush_transmit();
    if (flush_status != ActuatorLinkStatus::Ok) {
      return flush_status;
    }
  }

  ActuatorPacket packet{};
  const auto result = transport_.try_receive(packet.payload.data(),
                                              packet.payload.size());
  if (result.status != transport::TransportStatus::Ok) {
    return map_status(result.status);
  }
  if (result.bytes == 0U || result.bytes > packet.payload.size()) {
    return ActuatorLinkStatus::Error;
  }
  packet.size = static_cast<std::uint16_t>(result.bytes);
  packet.timestamp_ns = now_ns;
  return packets.push(packet) ? ActuatorLinkStatus::Ok
                              : ActuatorLinkStatus::Error;
}

ActuatorLinkStatus HalfDuplexSerialLink::transmit(
    std::int64_t, const ActuatorPacketBatch& packets) noexcept {
  if (!open_) {
    return ActuatorLinkStatus::Closed;
  }
  if (transmit_size_ != 0U) {
    return ActuatorLinkStatus::WouldBlock;
  }
  if (packets.empty()) {
    return ActuatorLinkStatus::Error;
  }

  std::size_t total = 0;
  for (std::size_t index = 0; index < packets.size(); ++index) {
    const auto& packet = packets[index];
    if (packet.size == 0U || packet.size > packet.payload.size() ||
        packet.size > transmit_buffer_.size() - total) {
      return ActuatorLinkStatus::Error;
    }
    std::memcpy(transmit_buffer_.data() + total, packet.payload.data(),
                packet.size);
    total += packet.size;
  }
  transmit_size_ = total;
  transmit_offset_ = 0;
  const auto status = flush_transmit();
  // WouldBlock means the complete transaction is retained in our fixed queue.
  return status == ActuatorLinkStatus::WouldBlock ? ActuatorLinkStatus::Ok
                                                   : status;
}

void HalfDuplexSerialLink::close() noexcept {
  transport_.close();
  open_ = false;
  transmit_size_ = 0;
  transmit_offset_ = 0;
}

}  // namespace rtctrl::hal
