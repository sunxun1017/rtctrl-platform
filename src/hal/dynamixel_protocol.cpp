#include "rtctrl/hal/dynamixel_protocol.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>

namespace rtctrl::hal {
namespace {

constexpr std::uint8_t kWriteInstruction = 0x03U;
constexpr std::uint8_t kSyncWriteInstruction = 0x83U;
constexpr std::uint8_t kBulkReadInstruction = 0x92U;
// A 256-byte ActuatorPacket must also hold worst-case byte stuffing (one byte
// added per FF FF FD pattern), header, instruction and CRC.
constexpr std::size_t kMaxStuffingSafeParameters = 180;

bool valid_register(DynamixelRegister reg, bool required) noexcept {
  if (!reg.present()) {
    return !required && reg.address == 0U;
  }
  return (reg.size == 1U || reg.size == 2U || reg.size == 4U) &&
         static_cast<std::uint32_t>(reg.address) + reg.size <= 0x10000U;
}

void append_u16(std::byte* output, std::size_t& cursor,
                std::uint16_t value) noexcept {
  output[cursor++] = static_cast<std::byte>(value & 0xffU);
  output[cursor++] = static_cast<std::byte>((value >> 8U) & 0xffU);
}

void append_integer(std::byte* output, std::size_t& cursor,
                    std::int32_t value, std::uint8_t size) noexcept {
  const auto raw = static_cast<std::uint32_t>(value);
  for (std::uint8_t index = 0; index < size; ++index) {
    output[cursor++] =
        static_cast<std::byte>((raw >> (8U * index)) & 0xffU);
  }
}

std::int32_t read_integer(const std::byte* input, std::uint8_t size) noexcept {
  std::uint32_t raw = 0;
  for (std::uint8_t index = 0; index < size; ++index) {
    raw |= static_cast<std::uint32_t>(
               static_cast<std::uint8_t>(input[index]))
           << (8U * index);
  }
  if (size == 1U) {
    return static_cast<std::int8_t>(raw);
  }
  if (size == 2U) {
    return static_cast<std::int16_t>(raw);
  }
  return static_cast<std::int32_t>(raw);
}

bool same_register(DynamixelRegister lhs, DynamixelRegister rhs) noexcept {
  return lhs.address == rhs.address && lhs.size == rhs.size;
}

}  // namespace

bool DynamixelProtocol2::feedback_window(
    const DynamixelJointProfile& joint, std::uint16_t& start,
    std::uint16_t& length) noexcept {
  if (!joint.present_position.present()) {
    return false;
  }
  std::uint32_t begin = joint.present_position.address;
  std::uint32_t end = begin + joint.present_position.size;
  const std::array<DynamixelRegister, 2> optional{
      joint.present_velocity, joint.present_effort};
  for (const auto reg : optional) {
    if (reg.present()) {
      begin = std::min(begin, static_cast<std::uint32_t>(reg.address));
      end = std::max(end, static_cast<std::uint32_t>(reg.address) + reg.size);
    }
  }
  if (end <= begin || end - begin > protocol::kDynamixelV2MaxParameters) {
    return false;
  }
  start = static_cast<std::uint16_t>(begin);
  length = static_cast<std::uint16_t>(end - begin);
  return true;
}

bool valid_dynamixel_protocol_config(
    const DynamixelProtocolConfig& config) noexcept {
  if (config.joints == nullptr || config.joint_count != model::kJointCount ||
      config.joint_count == 0U || config.joint_count > 64U) {
    return false;
  }
  for (std::size_t index = 0; index < config.joint_count; ++index) {
    const auto& joint = config.joints[index];
    if (joint.id > 0xfcU || joint.direction == 0 ||
        (joint.direction != 1 && joint.direction != -1) ||
        !valid_register(joint.torque_enable, true) ||
        joint.torque_enable.size != 1U ||
        !valid_register(joint.goal_position, true) ||
        !valid_register(joint.present_position, true) ||
        !valid_register(joint.present_velocity, false) ||
        !valid_register(joint.present_effort, false) ||
        !std::isfinite(joint.position_rad_per_unit) ||
        joint.position_rad_per_unit <= 0.0 ||
        (joint.present_velocity.present() &&
         (!std::isfinite(joint.velocity_rad_s_per_unit) ||
          joint.velocity_rad_s_per_unit <= 0.0)) ||
        (joint.present_effort.present() &&
         (!std::isfinite(joint.effort_nm_per_unit) ||
          joint.effort_nm_per_unit <= 0.0))) {
      return false;
    }
    std::uint16_t start = 0;
    std::uint16_t length = 0;
    if (!DynamixelProtocol2::feedback_window(joint, start, length)) {
      return false;
    }
    if (index != 0U &&
        (!same_register(config.joints[0].torque_enable,
                        joint.torque_enable) ||
         !same_register(config.joints[0].goal_position,
                        joint.goal_position))) {
      // Sync Write is required for deterministic half-duplex operation. Mixed
      // write layouts need separate buses or a deployment gateway.
      return false;
    }
    for (std::size_t previous = 0; previous < index; ++previous) {
      if (config.joints[previous].id == joint.id) {
        return false;
      }
    }
  }
  return true;
}

DynamixelProtocol2::DynamixelProtocol2(
    DynamixelProtocolConfig config) noexcept
    : config_(config), valid_(valid_dynamixel_protocol_config(config)) {}

void DynamixelProtocol2::reset() noexcept {
  parser_.reset();
  position_.fill(0.0);
  velocity_.fill(0.0);
  effort_.fill(0.0);
  seen_mask_ = 0;
  fault_bits_ = 0;
  sequence_ = 0;
}

bool DynamixelProtocol2::append_packet(
    std::uint8_t id, std::uint8_t instruction, const std::byte* parameters,
    std::size_t parameter_size, ActuatorPacketBatch& packets) noexcept {
  ActuatorPacket packet{};
  packet.endpoint = id;
  std::size_t wire_size = 0;
  if (!protocol::encode_dynamixel_v2_packet(
          id, instruction, parameters, parameter_size, packet.payload.data(),
          packet.payload.size(), wire_size) ||
      wire_size > std::numeric_limits<std::uint16_t>::max()) {
    return false;
  }
  packet.size = static_cast<std::uint16_t>(wire_size);
  return packets.push(packet);
}

bool DynamixelProtocol2::append_feedback_requests(
    ActuatorPacketBatch& packets) noexcept {
  std::array<std::byte, kMaxStuffingSafeParameters> parameters{};
  std::size_t cursor = 0;
  for (std::size_t index = 0; index < config_.joint_count; ++index) {
    if (cursor + 5U > parameters.size()) {
      if (!append_packet(protocol::kDynamixelBroadcastId,
                         kBulkReadInstruction, parameters.data(), cursor,
                         packets)) {
        return false;
      }
      cursor = 0;
    }
    std::uint16_t start = 0;
    std::uint16_t length = 0;
    if (!feedback_window(config_.joints[index], start, length)) {
      return false;
    }
    parameters[cursor++] = static_cast<std::byte>(config_.joints[index].id);
    append_u16(parameters.data(), cursor, start);
    append_u16(parameters.data(), cursor, length);
  }
  return cursor == 0U ||
         append_packet(protocol::kDynamixelBroadcastId, kBulkReadInstruction,
                       parameters.data(), cursor, packets);
}

bool DynamixelProtocol2::append_individual_write(
    std::size_t joint_index, DynamixelRegister reg, std::int32_t value,
    ActuatorPacketBatch& packets) noexcept {
  std::array<std::byte, 6> parameters{};
  std::size_t cursor = 0;
  append_u16(parameters.data(), cursor, reg.address);
  append_integer(parameters.data(), cursor, value, reg.size);
  return append_packet(config_.joints[joint_index].id, kWriteInstruction,
                       parameters.data(), cursor, packets);
}

bool DynamixelProtocol2::append_homogeneous_sync_write(
    DynamixelRegister reg,
    const std::array<std::int32_t, model::kJointCount>& values,
    ActuatorPacketBatch& packets) noexcept {
  std::array<std::byte, kMaxStuffingSafeParameters> parameters{};
  std::size_t joint = 0;
  while (joint < config_.joint_count) {
    std::size_t cursor = 0;
    append_u16(parameters.data(), cursor, reg.address);
    append_u16(parameters.data(), cursor, reg.size);
    do {
      parameters[cursor++] =
          static_cast<std::byte>(config_.joints[joint].id);
      append_integer(parameters.data(), cursor, values[joint], reg.size);
      ++joint;
    } while (joint < config_.joint_count &&
             cursor + 1U + reg.size <= parameters.size());
    if (!append_packet(protocol::kDynamixelBroadcastId,
                       kSyncWriteInstruction, parameters.data(), cursor,
                       packets)) {
      return false;
    }
  }
  return true;
}

bool DynamixelProtocol2::append_torque(
    bool enabled, ActuatorPacketBatch& packets) noexcept {
  std::array<std::int32_t, model::kJointCount> values{};
  values.fill(enabled ? 1 : 0);
  const auto reg = config_.joints[0].torque_enable;
  bool homogeneous = true;
  for (std::size_t index = 1; index < config_.joint_count; ++index) {
    homogeneous = homogeneous &&
                  same_register(reg, config_.joints[index].torque_enable);
  }
  if (homogeneous) {
    return append_homogeneous_sync_write(reg, values, packets);
  }
  for (std::size_t index = 0; index < config_.joint_count; ++index) {
    if (!append_individual_write(index, config_.joints[index].torque_enable,
                                 enabled ? 1 : 0, packets)) {
      return false;
    }
  }
  return true;
}

bool DynamixelProtocol2::append_positions(
    const model::CommandFrame& input,
    ActuatorPacketBatch& packets) noexcept {
  std::array<std::int32_t, model::kJointCount> values{};
  for (std::size_t index = 0; index < config_.joint_count; ++index) {
    const auto& joint = config_.joints[index];
    const auto raw = input.target_position[index] /
                         joint.position_rad_per_unit * joint.direction +
                     joint.position_zero_raw;
    if (!std::isfinite(raw) ||
        raw < static_cast<double>(std::numeric_limits<std::int32_t>::min()) ||
        raw > static_cast<double>(std::numeric_limits<std::int32_t>::max())) {
      return false;
    }
    if (joint.goal_position.size < 4U) {
      const auto max_raw = static_cast<double>(
          (std::uint32_t{1} << (8U * joint.goal_position.size)) - 1U);
      if (raw < 0.0 || raw > max_raw) {
        return false;
      }
    }
    values[index] = static_cast<std::int32_t>(std::llround(raw));
  }
  const auto reg = config_.joints[0].goal_position;
  bool homogeneous = true;
  for (std::size_t index = 1; index < config_.joint_count; ++index) {
    homogeneous = homogeneous &&
                  same_register(reg, config_.joints[index].goal_position);
  }
  if (homogeneous) {
    return append_homogeneous_sync_write(reg, values, packets);
  }
  for (std::size_t index = 0; index < config_.joint_count; ++index) {
    if (!append_individual_write(index, config_.joints[index].goal_position,
                                 values[index], packets)) {
      return false;
    }
  }
  return true;
}

ActuatorProtocolStatus DynamixelProtocol2::encode_startup(
    std::int64_t, ActuatorPacketBatch& packets) noexcept {
  packets.clear();
  return valid_ && append_feedback_requests(packets)
             ? ActuatorProtocolStatus::Ok
             : ActuatorProtocolStatus::InvalidData;
}

ActuatorProtocolStatus DynamixelProtocol2::encode_arm(
    std::int64_t, ActuatorPacketBatch& packets) noexcept {
  packets.clear();
  return valid_ && append_torque(true, packets) &&
                 append_feedback_requests(packets)
             ? ActuatorProtocolStatus::Ok
             : ActuatorProtocolStatus::InvalidData;
}

ActuatorProtocolStatus DynamixelProtocol2::encode_command(
    std::int64_t, const model::CommandFrame& input,
    ActuatorPacketBatch& packets) noexcept {
  packets.clear();
  if (!valid_) {
    return ActuatorProtocolStatus::InvalidData;
  }
  if (input.mode == model::CommandMode::SafeStop) {
    return append_torque(false, packets)
               ? ActuatorProtocolStatus::Ok
               : ActuatorProtocolStatus::InvalidData;
  }
  if (input.mode != model::CommandMode::Position ||
      !append_positions(input, packets) ||
      !append_feedback_requests(packets)) {
    return ActuatorProtocolStatus::InvalidData;
  }
  return ActuatorProtocolStatus::Ok;
}

ActuatorProtocolStatus DynamixelProtocol2::encode_safe_stop(
    std::int64_t, ActuatorPacketBatch& packets) noexcept {
  packets.clear();
  return valid_ && append_torque(false, packets)
             ? ActuatorProtocolStatus::Ok
             : ActuatorProtocolStatus::InvalidData;
}

bool DynamixelProtocol2::find_joint(std::uint8_t id,
                                    std::size_t& index) const noexcept {
  for (std::size_t candidate = 0; candidate < config_.joint_count; ++candidate) {
    if (config_.joints[candidate].id == id) {
      index = candidate;
      return true;
    }
  }
  return false;
}

ActuatorProtocolStatus DynamixelProtocol2::decode_feedback(
    std::int64_t now_ns, const ActuatorPacketBatch& packets,
    model::SensorFrame& output) noexcept {
  if (!valid_) {
    return ActuatorProtocolStatus::InvalidData;
  }
  protocol::DynamixelV2Packet packet{};
  const auto process_packet = [&](const protocol::DynamixelV2Packet& value) {
    if (value.instruction != protocol::kDynamixelStatusInstruction) {
      return true;
    }
    std::size_t joint_index = 0;
    if (!find_joint(value.id, joint_index)) {
      return true;
    }
    const auto& joint = config_.joints[joint_index];
    std::uint16_t start = 0;
    std::uint16_t length = 0;
    if (!feedback_window(joint, start, length) ||
        value.parameter_size < length) {
      if (value.error != 0U) {
        fault_bits_ |= std::uint64_t{1} << joint_index;
      }
      // A short status packet can be an acknowledgement for an individual
      // setup write. It is not a feedback sample.
      return true;
    }
    const auto decode = [&](DynamixelRegister reg) noexcept {
      return read_integer(value.parameters.data() + (reg.address - start),
                          reg.size);
    };
    position_[joint_index] =
        (static_cast<double>(decode(joint.present_position)) -
         static_cast<double>(joint.position_zero_raw)) *
        joint.position_rad_per_unit * joint.direction;
    velocity_[joint_index] = joint.present_velocity.present()
                                 ? static_cast<double>(decode(
                                       joint.present_velocity)) *
                                       joint.velocity_rad_s_per_unit *
                                       joint.direction
                                 : 0.0;
    effort_[joint_index] = joint.present_effort.present()
                               ? static_cast<double>(decode(
                                     joint.present_effort)) *
                                     joint.effort_nm_per_unit * joint.direction
                               : 0.0;
    if (value.error != 0U) {
      fault_bits_ |= std::uint64_t{1} << joint_index;
    }
    seen_mask_ |= std::uint64_t{1} << joint_index;
    return true;
  };

  for (std::size_t index = 0; index < packets.size(); ++index) {
    if (!parser_.push(packets[index].payload.data(), packets[index].size)) {
      parser_.reset();
      seen_mask_ = 0;
      return ActuatorProtocolStatus::InvalidData;
    }
    while (parser_.pop(packet)) {
      if (!process_packet(packet)) {
        return ActuatorProtocolStatus::InvalidData;
      }
    }
  }

  const auto expected_mask = config_.joint_count == 64U
                                 ? std::numeric_limits<std::uint64_t>::max()
                                 : (std::uint64_t{1} << config_.joint_count) - 1U;
  if (seen_mask_ != expected_mask) {
    return ActuatorProtocolStatus::NotReady;
  }
  output = {};
  output.sequence = ++sequence_;
  output.sample_time_ns = now_ns;
  output.position = position_;
  output.velocity = velocity_;
  output.effort = effort_;
  output.fault_bits = fault_bits_;
  seen_mask_ = 0;
  fault_bits_ = 0;
  return ActuatorProtocolStatus::Ok;
}

}  // namespace rtctrl::hal
