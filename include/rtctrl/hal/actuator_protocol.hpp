#pragma once

#include "rtctrl/hal/actuator_link.hpp"
#include "rtctrl/model/frames.hpp"

#include <cstdint>

namespace rtctrl::hal {

enum class ActuatorProtocolStatus : std::uint8_t {
  Ok,
  NotReady,
  InvalidData,
};

struct ActuatorProtocolRequirements {
  std::size_t max_payload_size{0};
  std::size_t max_packets_per_cycle{0};
};

// A motor/device-family codec. It owns command words, register layout, units,
// scaling and feedback validation, but it does not open or identify a physical
// communication bus.
class IActuatorProtocol {
public:
  virtual ~IActuatorProtocol() = default;

  // Queried only during composition. It makes invalid protocol/link pairings a
  // startup error rather than a truncated packet in the realtime loop.
  virtual ActuatorProtocolRequirements requirements() const noexcept = 0;
  virtual void reset() noexcept = 0;
  // Optional initial feedback request sent by open_safe(). An empty batch
  // means the protocol receives unsolicited feedback and needs no request.
  virtual ActuatorProtocolStatus encode_startup(
      std::int64_t now_ns, ActuatorPacketBatch& packets) noexcept = 0;
  virtual ActuatorProtocolStatus decode_feedback(
      std::int64_t now_ns, const ActuatorPacketBatch& packets,
      model::SensorFrame& output) noexcept = 0;
  virtual ActuatorProtocolStatus encode_arm(
      std::int64_t now_ns, ActuatorPacketBatch& packets) noexcept = 0;
  virtual ActuatorProtocolStatus encode_command(
      std::int64_t now_ns, const model::CommandFrame& input,
      ActuatorPacketBatch& packets) noexcept = 0;
  virtual ActuatorProtocolStatus encode_safe_stop(
      std::int64_t now_ns, ActuatorPacketBatch& packets) noexcept = 0;
};

}  // namespace rtctrl::hal
