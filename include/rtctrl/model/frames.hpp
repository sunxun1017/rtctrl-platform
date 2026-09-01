#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace rtctrl::model {

#ifndef RTCTRL_JOINT_COUNT
#define RTCTRL_JOINT_COUNT 6
#endif

static_assert(RTCTRL_JOINT_COUNT >= 1 && RTCTRL_JOINT_COUNT <= 64,
              "RTCTRL_JOINT_COUNT must be in [1, 64]");
constexpr std::size_t kJointCount = RTCTRL_JOINT_COUNT;

enum class CommandMode : std::uint8_t { Disabled = 0, Position = 1, SafeStop = 2 };

struct SensorFrame {
  std::uint64_t sequence{0};
  std::int64_t sample_time_ns{0};
  std::array<double, kJointCount> position{};
  std::array<double, kJointCount> velocity{};
  std::array<double, kJointCount> effort{};
  std::uint64_t fault_bits{0};
};

struct CommandFrame {
  std::uint64_t sequence{0};
  std::int64_t created_time_ns{0};
  std::int64_t valid_until_ns{0};
  CommandMode mode{CommandMode::Disabled};
  std::array<double, kJointCount> target_position{};
  std::array<double, kJointCount> target_velocity{};
  std::array<double, kJointCount> effort{};
  std::array<double, kJointCount> kp{};
  std::array<double, kJointCount> kd{};
};

struct ControlTarget {
  std::uint64_t sequence{0};
  std::int64_t created_time_ns{0};
  // Zero means "use the local runtime lease". Positive values are an
  // end-to-end deadline carried by framed transports.
  std::int64_t valid_until_ns{0};
  std::array<double, kJointCount> position{};
};

static_assert(std::is_trivially_copyable_v<SensorFrame>);
static_assert(std::is_trivially_copyable_v<CommandFrame>);
static_assert(std::is_trivially_copyable_v<ControlTarget>);

}  // namespace rtctrl::model
