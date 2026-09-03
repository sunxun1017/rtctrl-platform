#pragma once

#include "rtctrl/hal/actuator_hal.hpp"
#include "rtctrl/hal/actuator_link.hpp"
#include "rtctrl/hal/actuator_protocol.hpp"

namespace rtctrl::hal {

// The only layer that joins a device protocol to a communication link. Both
// dependencies are supplied by the non-realtime composition root.
class ProtocolActuatorHal final : public IActuatorHal {
public:
  ProtocolActuatorHal(IActuatorLink& link,
                      IActuatorProtocol& protocol) noexcept
      : link_(link), protocol_(protocol) {}

  HalStatus open_safe(std::int64_t now_ns) noexcept override;
  HalStatus arm(std::int64_t now_ns) noexcept override;
  HalStatus read(std::int64_t now_ns,
                 model::SensorFrame& output) noexcept override;
  HalStatus write(std::int64_t now_ns,
                  const model::CommandFrame& input) noexcept override;
  void emergency_stop(std::int64_t now_ns) noexcept override;
  void close() noexcept override;

private:
  static HalStatus map_link_status(ActuatorLinkStatus status) noexcept;
  static HalStatus map_protocol_status(
      ActuatorProtocolStatus status) noexcept;

  IActuatorLink& link_;
  IActuatorProtocol& protocol_;
  ActuatorPacketBatch receive_packets_{};
  ActuatorPacketBatch transmit_packets_{};
  bool open_{false};
  bool feedback_ready_{false};
  bool armed_{false};
};

}  // namespace rtctrl::hal
