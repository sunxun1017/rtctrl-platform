#pragma once

#include "rtctrl/model/frames.hpp"

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <new>
#include <type_traits>

namespace rtctrl::ipc {

constexpr std::uint32_t kSharedMotorMagic = 0x4d435452U; // "RTCM" on LE hosts.
constexpr std::uint32_t kSharedMotorAbiVersion = 2;
constexpr int kSnapshotReadAttempts = 8;

struct HybridJointCommand {
    double position{0.0};
    double velocity{0.0};
    double effort{0.0};
    double kp{0.0};
    double kd{0.0};
};

struct JointFeedback {
    double position{0.0};
    double velocity{0.0};
    double effort{0.0};
    double temperature_c{0.0};
    std::uint32_t error_flags{0};
};

struct ImuSample {
    std::array<double, 4> orientation_xyzw{0.0, 0.0, 0.0, 1.0};
    std::array<double, 3> angular_velocity{};
    std::array<double, 3> linear_acceleration{};
    std::int64_t sample_time_ns{0};
};

struct AtomicDouble {
    void store(double value, std::memory_order order = std::memory_order_relaxed) noexcept {
        std::uint64_t encoded = 0;
        std::memcpy(&encoded, &value, sizeof(encoded));
        bits.store(encoded, order);
    }
    double load(std::memory_order order = std::memory_order_relaxed) const noexcept {
        const auto encoded = bits.load(order);
        double value = 0.0;
        std::memcpy(&value, &encoded, sizeof(value));
        return value;
    }
    std::atomic<std::uint64_t> bits{0};
};

struct AtomicHybridJointCommand {
    AtomicDouble position;
    AtomicDouble velocity;
    AtomicDouble effort;
    AtomicDouble kp;
    AtomicDouble kd;
};

struct AtomicJointFeedback {
    AtomicDouble position;
    AtomicDouble velocity;
    AtomicDouble effort;
    AtomicDouble temperature_c;
    std::atomic<std::uint32_t> error_flags{0};
};

struct AtomicImuSample {
    std::array<AtomicDouble, 4> orientation_xyzw;
    std::array<AtomicDouble, 3> angular_velocity;
    std::array<AtomicDouble, 3> linear_acceleration;
    std::atomic<std::int64_t> sample_time_ns{0};
};

// ABI between a ROS-free L0 hardware process and an optional controller/ROS
// process. Each direction has exactly one writer and one reader. Fields are
// append-only; changing an existing field requires an ABI version bump.
struct SharedMotorRegion {
    SharedMotorRegion() noexcept;

    std::uint32_t magic{kSharedMotorMagic};
    std::uint32_t abi_version{kSharedMotorAbiVersion};
    std::uint32_t region_size{0};
    std::uint32_t joint_count{static_cast<std::uint32_t>(model::kJointCount)};

    alignas(64) std::atomic<std::uint32_t> command_seq{0};
    std::atomic<std::uint64_t> command_generation{0};
    std::atomic<std::int64_t> command_created_ns{0};
    std::atomic<std::int64_t> command_valid_until_ns{0};
    std::array<AtomicHybridJointCommand, model::kJointCount> command{};
    std::atomic<std::uint32_t> motor_enable{0};

    alignas(64) std::atomic<std::uint32_t> feedback_seq{0};
    std::atomic<std::uint64_t> feedback_generation{0};
    std::atomic<std::int64_t> feedback_sample_time_ns{0};
    std::array<AtomicJointFeedback, model::kJointCount> feedback{};
    AtomicImuSample imu{};

    alignas(64) std::atomic<std::uint64_t> l0_cycle_counter{0};
    std::atomic<std::uint32_t> l0_fault_code{0};
};

inline SharedMotorRegion::SharedMotorRegion() noexcept
    : region_size(static_cast<std::uint32_t>(sizeof(SharedMotorRegion))) {}

struct CommandSnapshot {
    std::uint64_t generation{0};
    std::int64_t created_ns{0};
    std::int64_t valid_until_ns{0};
    std::array<HybridJointCommand, model::kJointCount> joints{};
};

struct FeedbackSnapshot {
    std::uint64_t generation{0};
    std::int64_t sample_time_ns{0};
    std::array<JointFeedback, model::kJointCount> joints{};
    ImuSample imu{};
};

static_assert(std::is_standard_layout_v<HybridJointCommand>);
static_assert(std::is_standard_layout_v<JointFeedback>);
static_assert(std::atomic<std::uint32_t>::is_always_lock_free,
              "shared snapshot protocol requires lock-free uint32 atomics");
static_assert(std::atomic<std::uint64_t>::is_always_lock_free,
              "shared liveness counter requires lock-free uint64 atomics");
static_assert(std::atomic<std::int64_t>::is_always_lock_free,
              "shared timestamps require lock-free int64 atomics");

inline bool valid_shared_motor_region(const SharedMotorRegion& region) noexcept {
    return region.magic == kSharedMotorMagic && region.abi_version == kSharedMotorAbiVersion &&
           region.region_size == sizeof(SharedMotorRegion) &&
           region.joint_count == model::kJointCount;
}

inline void initialize_shared_motor_region(SharedMotorRegion& region) noexcept {
    new (&region) SharedMotorRegion();
}

inline void publish_command(SharedMotorRegion& region, const CommandSnapshot& input) noexcept {
    const auto sequence = region.command_seq.load(std::memory_order_relaxed);
    region.command_seq.store(sequence + 1U, std::memory_order_release);
    std::atomic_thread_fence(std::memory_order_release);
    region.command_generation.store(input.generation, std::memory_order_relaxed);
    region.command_created_ns.store(input.created_ns, std::memory_order_relaxed);
    region.command_valid_until_ns.store(input.valid_until_ns, std::memory_order_relaxed);
    for (std::size_t i = 0; i < model::kJointCount; ++i) {
        region.command[i].position.store(input.joints[i].position);
        region.command[i].velocity.store(input.joints[i].velocity);
        region.command[i].effort.store(input.joints[i].effort);
        region.command[i].kp.store(input.joints[i].kp);
        region.command[i].kd.store(input.joints[i].kd);
    }
    std::atomic_thread_fence(std::memory_order_release);
    region.command_seq.store(sequence + 2U, std::memory_order_release);
}

inline bool read_command(const SharedMotorRegion& region, CommandSnapshot& output) noexcept {
    for (int attempt = 0; attempt < kSnapshotReadAttempts; ++attempt) {
        const auto before = region.command_seq.load(std::memory_order_acquire);
        if ((before & 1U) != 0U) {
            continue;
        }
        output.generation = region.command_generation.load(std::memory_order_relaxed);
        output.created_ns = region.command_created_ns.load(std::memory_order_relaxed);
        output.valid_until_ns = region.command_valid_until_ns.load(std::memory_order_relaxed);
        for (std::size_t i = 0; i < model::kJointCount; ++i) {
            output.joints[i].position = region.command[i].position.load();
            output.joints[i].velocity = region.command[i].velocity.load();
            output.joints[i].effort = region.command[i].effort.load();
            output.joints[i].kp = region.command[i].kp.load();
            output.joints[i].kd = region.command[i].kd.load();
        }
        std::atomic_thread_fence(std::memory_order_acquire);
        const auto after = region.command_seq.load(std::memory_order_relaxed);
        if (before == after) {
            return true;
        }
    }
    return false;
}

inline void publish_feedback(SharedMotorRegion& region, const FeedbackSnapshot& input) noexcept {
    const auto sequence = region.feedback_seq.load(std::memory_order_relaxed);
    region.feedback_seq.store(sequence + 1U, std::memory_order_release);
    std::atomic_thread_fence(std::memory_order_release);
    region.feedback_generation.store(input.generation, std::memory_order_relaxed);
    region.feedback_sample_time_ns.store(input.sample_time_ns, std::memory_order_relaxed);
    for (std::size_t i = 0; i < model::kJointCount; ++i) {
        region.feedback[i].position.store(input.joints[i].position);
        region.feedback[i].velocity.store(input.joints[i].velocity);
        region.feedback[i].effort.store(input.joints[i].effort);
        region.feedback[i].temperature_c.store(input.joints[i].temperature_c);
        region.feedback[i].error_flags.store(input.joints[i].error_flags,
                                             std::memory_order_relaxed);
    }
    for (std::size_t i = 0; i < input.imu.orientation_xyzw.size(); ++i) {
        region.imu.orientation_xyzw[i].store(input.imu.orientation_xyzw[i]);
    }
    for (std::size_t i = 0; i < input.imu.angular_velocity.size(); ++i) {
        region.imu.angular_velocity[i].store(input.imu.angular_velocity[i]);
        region.imu.linear_acceleration[i].store(input.imu.linear_acceleration[i]);
    }
    region.imu.sample_time_ns.store(input.imu.sample_time_ns, std::memory_order_relaxed);
    std::atomic_thread_fence(std::memory_order_release);
    region.feedback_seq.store(sequence + 2U, std::memory_order_release);
}

inline bool read_feedback(const SharedMotorRegion& region, FeedbackSnapshot& output) noexcept {
    for (int attempt = 0; attempt < kSnapshotReadAttempts; ++attempt) {
        const auto before = region.feedback_seq.load(std::memory_order_acquire);
        if ((before & 1U) != 0U) {
            continue;
        }
        output.generation = region.feedback_generation.load(std::memory_order_relaxed);
        output.sample_time_ns = region.feedback_sample_time_ns.load(std::memory_order_relaxed);
        for (std::size_t i = 0; i < model::kJointCount; ++i) {
            output.joints[i].position = region.feedback[i].position.load();
            output.joints[i].velocity = region.feedback[i].velocity.load();
            output.joints[i].effort = region.feedback[i].effort.load();
            output.joints[i].temperature_c = region.feedback[i].temperature_c.load();
            output.joints[i].error_flags =
                region.feedback[i].error_flags.load(std::memory_order_relaxed);
        }
        for (std::size_t i = 0; i < output.imu.orientation_xyzw.size(); ++i) {
            output.imu.orientation_xyzw[i] = region.imu.orientation_xyzw[i].load();
        }
        for (std::size_t i = 0; i < output.imu.angular_velocity.size(); ++i) {
            output.imu.angular_velocity[i] = region.imu.angular_velocity[i].load();
            output.imu.linear_acceleration[i] = region.imu.linear_acceleration[i].load();
        }
        output.imu.sample_time_ns = region.imu.sample_time_ns.load(std::memory_order_relaxed);
        std::atomic_thread_fence(std::memory_order_acquire);
        const auto after = region.feedback_seq.load(std::memory_order_relaxed);
        if (before == after) {
            return true;
        }
    }
    return false;
}

} // namespace rtctrl::ipc
