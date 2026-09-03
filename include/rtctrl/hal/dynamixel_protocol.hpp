#pragma once

#include "rtctrl/hal/actuator_protocol.hpp"
#include "rtctrl/protocol/dynamixel_v2.hpp"

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::hal {

struct DynamixelRegister {
  std::uint16_t address{0};
  std::uint8_t size{0};

  bool present() const noexcept { return size != 0U; }
};

// One deployment entry per logical joint. Control-table addresses and unit
// conversions are model data; the serial device and baud rate are not.
struct DynamixelJointProfile {
  std::uint8_t id{0};
  DynamixelRegister torque_enable{};
  DynamixelRegister goal_position{};
  DynamixelRegister present_position{};
  DynamixelRegister present_velocity{};
  DynamixelRegister present_effort{};
  std::int32_t position_zero_raw{0};
  double position_rad_per_unit{0.0};
  double velocity_rad_s_per_unit{0.0};
  double effort_nm_per_unit{0.0};
  std::int8_t direction{1};
};

struct DynamixelProtocolConfig {
  const DynamixelJointProfile* joints{nullptr};
  std::size_t joint_count{0};
};

bool valid_dynamixel_protocol_config(
    const DynamixelProtocolConfig& config) noexcept;

class DynamixelProtocol2 final : public IActuatorProtocol {
public:
  explicit DynamixelProtocol2(DynamixelProtocolConfig config) noexcept;

  ActuatorProtocolRequirements requirements() const noexcept override {
    return {kActuatorPacketPayloadCapacity, kActuatorPacketBatchCapacity};
  }
  void reset() noexcept override;
  ActuatorProtocolStatus encode_startup(
      std::int64_t now_ns, ActuatorPacketBatch& packets) noexcept override;
  ActuatorProtocolStatus decode_feedback(
      std::int64_t now_ns, const ActuatorPacketBatch& packets,
      model::SensorFrame& output) noexcept override;
  ActuatorProtocolStatus encode_arm(
      std::int64_t now_ns, ActuatorPacketBatch& packets) noexcept override;
  ActuatorProtocolStatus encode_command(
      std::int64_t now_ns, const model::CommandFrame& input,
      ActuatorPacketBatch& packets) noexcept override;
  ActuatorProtocolStatus encode_safe_stop(
      std::int64_t now_ns, ActuatorPacketBatch& packets) noexcept override;

  bool valid() const noexcept { return valid_; }
  static bool feedback_window(const DynamixelJointProfile& joint,
                              std::uint16_t& start,
                              std::uint16_t& length) noexcept;

private:
  bool append_packet(std::uint8_t id, std::uint8_t instruction,
                     const std::byte* parameters, std::size_t parameter_size,
                     ActuatorPacketBatch& packets) noexcept;
  bool append_feedback_requests(ActuatorPacketBatch& packets) noexcept;
  bool append_torque(bool enabled, ActuatorPacketBatch& packets) noexcept;
  bool append_positions(const model::CommandFrame& input,
                        ActuatorPacketBatch& packets) noexcept;
  bool append_individual_write(std::size_t joint_index,
                               DynamixelRegister reg, std::int32_t value,
                               ActuatorPacketBatch& packets) noexcept;
  bool append_homogeneous_sync_write(
      DynamixelRegister reg, const std::array<std::int32_t,
      model::kJointCount>& values, ActuatorPacketBatch& packets) noexcept;
  bool find_joint(std::uint8_t id, std::size_t& index) const noexcept;
  DynamixelProtocolConfig config_{};
  protocol::DynamixelV2StreamParser parser_{};
  std::array<double, model::kJointCount> position_{};
  std::array<double, model::kJointCount> velocity_{};
  std::array<double, model::kJointCount> effort_{};
  std::uint64_t seen_mask_{0};
  std::uint64_t fault_bits_{0};
  std::uint64_t sequence_{0};
  bool valid_{false};
};

}  // namespace rtctrl::hal
