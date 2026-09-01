#include "rtctrl/hal/shared_memory_hal.hpp"

#include <cmath>

namespace rtctrl::hal {

HalStatus SharedMemoryHal::open_safe(std::int64_t) noexcept {
  if (!ipc::valid_shared_motor_region(region_) ||
      config_.max_feedback_age_ns <= 0) {
    return HalStatus::IoError;
  }
  region_.motor_enable.store(0, std::memory_order_release);
  opened_ = true;
  armed_ = false;
  have_feedback_ = false;
  return HalStatus::Ok;
}

HalStatus SharedMemoryHal::arm(std::int64_t) noexcept {
  if (!opened_ || !have_feedback_ ||
      region_.l0_fault_code.load(std::memory_order_acquire) != 0U) {
    return HalStatus::NotReady;
  }
  region_.motor_enable.store(1, std::memory_order_release);
  armed_ = true;
  return HalStatus::Ok;
}

HalStatus SharedMemoryHal::read(std::int64_t now_ns,
                                model::SensorFrame& output) noexcept {
  if (!opened_) {
    return HalStatus::NotReady;
  }
  ipc::FeedbackSnapshot snapshot{};
  if (!ipc::read_feedback(region_, snapshot) || snapshot.generation == 0 ||
      snapshot.sample_time_ns > now_ns ||
      now_ns - snapshot.sample_time_ns > config_.max_feedback_age_ns) {
    return HalStatus::IoError;
  }

  output = {};
  output.sequence = snapshot.generation;
  output.sample_time_ns = snapshot.sample_time_ns;
  output.fault_bits = region_.l0_fault_code.load(std::memory_order_acquire);
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    const auto& joint = snapshot.joints[i];
    output.position[i] = joint.position;
    output.velocity[i] = joint.velocity;
    output.effort[i] = joint.effort;
    if (joint.error_flags != 0U) {
      output.fault_bits |= 1ULL << (i % 63U);
    }
  }
  last_feedback_ = snapshot;
  have_feedback_ = true;
  return output.fault_bits == 0 ? HalStatus::Ok : HalStatus::IoError;
}

HalStatus SharedMemoryHal::write(std::int64_t now_ns,
                                 const model::CommandFrame& input) noexcept {
  if (!opened_ || !armed_ || input.mode != model::CommandMode::Position ||
      input.created_time_ns > now_ns || input.valid_until_ns < now_ns) {
    return HalStatus::NotReady;
  }
  ipc::CommandSnapshot snapshot{};
  snapshot.generation = input.sequence;
  snapshot.created_ns = input.created_time_ns;
  snapshot.valid_until_ns = input.valid_until_ns;
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    snapshot.joints[i] = {input.target_position[i], input.target_velocity[i],
                          input.effort[i], input.kp[i], input.kd[i]};
  }
  ipc::publish_command(region_, snapshot);
  return HalStatus::Ok;
}

void SharedMemoryHal::emergency_stop(std::int64_t now_ns) noexcept {
  region_.motor_enable.store(0, std::memory_order_release);
  if (!opened_) {
    return;
  }
  ipc::CommandSnapshot safe{};
  safe.generation = last_feedback_.generation + 1;
  safe.created_ns = now_ns;
  safe.valid_until_ns = now_ns + 1'000'000;
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    const double position = last_feedback_.joints[i].position;
    safe.joints[i].position = std::isfinite(position) ? position : 0.0;
  }
  ipc::publish_command(region_, safe);
  armed_ = false;
}

void SharedMemoryHal::close() noexcept {
  region_.motor_enable.store(0, std::memory_order_release);
  opened_ = false;
  armed_ = false;
  have_feedback_ = false;
}

}  // namespace rtctrl::hal
