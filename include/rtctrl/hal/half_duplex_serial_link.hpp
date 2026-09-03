#pragma once

#include "rtctrl/hal/actuator_link.hpp"
#include "rtctrl/transport/byte_transport.hpp"

#include <array>
#include <cstddef>

namespace rtctrl::hal {

// A bounded raw-packet adapter for half-duplex UART/RS-485. Electrical
// direction switching is owned by the underlying transport/adapter hardware.
// Each ActuatorPacket payload is already a complete wire-protocol packet.
class HalfDuplexSerialLink final : public IActuatorLink {
public:
  static constexpr std::size_t kTransmitCapacity = 4096;

  explicit HalfDuplexSerialLink(
      transport::IByteTransport& transport) noexcept
      : transport_(transport) {}

  ActuatorLinkCapabilities capabilities() const noexcept override {
    return {kActuatorPacketPayloadCapacity, kActuatorPacketBatchCapacity};
  }
  ActuatorLinkStatus open() noexcept override;
  ActuatorLinkStatus receive(std::int64_t now_ns,
                             ActuatorPacketBatch& packets) noexcept override;
  ActuatorLinkStatus transmit(
      std::int64_t now_ns,
      const ActuatorPacketBatch& packets) noexcept override;
  void close() noexcept override;

private:
  ActuatorLinkStatus flush_transmit() noexcept;
  static ActuatorLinkStatus map_status(
      transport::TransportStatus status) noexcept;

  transport::IByteTransport& transport_;
  std::array<std::byte, kTransmitCapacity> transmit_buffer_{};
  std::size_t transmit_size_{0};
  std::size_t transmit_offset_{0};
  bool open_{false};
};

}  // namespace rtctrl::hal
