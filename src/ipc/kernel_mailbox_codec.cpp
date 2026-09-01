#include "rtctrl/ipc/kernel_mailbox_codec.hpp"

#include <cmath>
#include <cstddef>
#include <limits>

namespace rtctrl::ipc {
namespace {

bool to_float(double input, float& output) noexcept {
  constexpr double max_float = static_cast<double>(std::numeric_limits<float>::max());
  if (!std::isfinite(input) || input < -max_float || input > max_float) {
    return false;
  }
  output = static_cast<float>(input);
  return std::isfinite(output);
}

}  // namespace

MailboxFrameStatus encode_mailbox_command(
    const model::CommandFrame& input,
    rtctrl_mb_command_frame& output) noexcept {
  if (input.sequence == 0 || input.created_time_ns < 0 ||
      input.valid_until_ns < input.created_time_ns ||
      (input.mode != model::CommandMode::Position &&
       input.mode != model::CommandMode::SafeStop)) {
    return MailboxFrameStatus::InvalidFrame;
  }
  rtctrl_mb_command_frame next{};
  next.sequence = input.sequence;
  next.created_time_ns = static_cast<std::uint64_t>(input.created_time_ns);
  next.valid_until_ns = static_cast<std::uint64_t>(input.valid_until_ns);
  next.joint_count = static_cast<std::uint32_t>(model::kJointCount);
  next.flags = input.mode == model::CommandMode::SafeStop
                   ? RTCTRL_MB_COMMAND_FLAG_SAFE_STOP
                   : RTCTRL_MB_COMMAND_FLAG_POSITION;
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    auto& joint = next.joint[i];
    if (!to_float(input.target_position[i], joint.position) ||
        !to_float(input.target_velocity[i], joint.velocity) ||
        !to_float(input.effort[i], joint.effort) ||
        !to_float(input.kp[i], joint.kp) ||
        !to_float(input.kd[i], joint.kd)) {
      return MailboxFrameStatus::InvalidFrame;
    }
  }
  output = next;
  return MailboxFrameStatus::Ok;
}

MailboxFrameStatus decode_mailbox_feedback(
    const rtctrl_mb_feedback_frame& input, std::int64_t now_ns,
    std::int64_t max_age_ns, model::SensorFrame& output) noexcept {
  if (input.sequence == 0 ||
      input.joint_count != static_cast<std::uint32_t>(model::kJointCount)) {
    return MailboxFrameStatus::InvalidFrame;
  }
  if (now_ns < 0 || max_age_ns <= 0 ||
      input.sample_time_ns > static_cast<std::uint64_t>(now_ns) ||
      static_cast<std::uint64_t>(now_ns) - input.sample_time_ns >
          static_cast<std::uint64_t>(max_age_ns)) {
    return MailboxFrameStatus::Stale;
  }
  model::SensorFrame next{};
  next.sequence = input.sequence;
  next.sample_time_ns = static_cast<std::int64_t>(input.sample_time_ns);
  next.fault_bits = input.fault_bits;
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    const auto& joint = input.joint[i];
    if (!std::isfinite(joint.position) || !std::isfinite(joint.velocity) ||
        !std::isfinite(joint.effort)) {
      return MailboxFrameStatus::InvalidFrame;
    }
    next.position[i] = joint.position;
    next.velocity[i] = joint.velocity;
    next.effort[i] = joint.effort;
    if (joint.error_flags != 0U) {
      next.fault_bits |= 1ULL << (i % 63U);
    }
  }
  output = next;
  return MailboxFrameStatus::Ok;
}

}  // namespace rtctrl::ipc
