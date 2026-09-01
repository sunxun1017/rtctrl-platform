#include "rtctrl/control/joint_pd.hpp"
#include "rtctrl/control/policy_action_mapper.hpp"
#include "rtctrl/hal/simulated_hal.hpp"
#include "rtctrl/hal/shared_memory_hal.hpp"
#include "rtctrl/ipc/shared_motor_abi.hpp"
#include "rtctrl/ipc/posix_shared_memory.hpp"
#include "rtctrl/ipc/kernel_mailbox_codec.hpp"
#include "rtctrl/ipc/spsc_ring.hpp"
#include "rtctrl/platform/posix_realtime.hpp"
#include "rtctrl/protocol/fixed_target_codec.hpp"
#include "rtctrl/profiles/yidong23_topology.hpp"
#include "rtctrl/runtime/realtime_engine.hpp"
#include "rtctrl/safety/safety_policy.hpp"
#include "rtctrl/transport/command_source.hpp"
#include "rtctrl/transport/framed_command_source.hpp"
#include "rtctrl/transport/loopback_byte_transport.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <limits>
#include <thread>
#include <unistd.h>

namespace {

int failures = 0;

void expect(bool condition, const char* message) {
  if (!condition) {
    ++failures;
    std::cerr << "FAIL: " << message << '\n';
  }
}

void test_spsc_ring() {
  rtctrl::ipc::SpscRing<int, 4> queue;
  expect(queue.try_push(1), "push 1");
  expect(queue.try_push(2), "push 2");
  expect(queue.try_push(3), "push 3");
  expect(queue.try_push(4), "push 4");
  expect(!queue.try_push(5), "bounded queue rejects overflow");
  int value = 0;
  expect(queue.try_pop(value) && value == 1, "FIFO pop");
  expect(queue.try_push(5), "wrap-around push");
  expect(queue.drain_latest(value) && value == 5, "drain_latest keeps newest value");
  expect(!queue.try_pop(value), "queue empty after drain");
}

class FakeRealtimePlatform final : public rtctrl::platform::IRealtimePlatform {
public:
  std::int64_t now_ns() const noexcept override { return now_; }
  rtctrl::platform::MemoryLockReport lock_process_memory() noexcept override {
    return {true, 0};
  }
  rtctrl::platform::ThreadSetupReport configure_current_thread(
      const rtctrl::platform::ThreadConfig&) noexcept override {
    return {true, true, 0, 0};
  }
  void prefault_stack() noexcept override {}
  int sleep_until(std::int64_t deadline_ns) noexcept override {
    now_ = deadline_ns + overshoot_ns;
    return 0;
  }

  std::int64_t now_{0};
  std::int64_t overshoot_ns{0};
};

void test_platform_independent_timer() {
  FakeRealtimePlatform platform;
  rtctrl::platform::PeriodicTimer timer(platform, 1'000);
  const auto first = timer.wait_next();
  expect(first.scheduled_ns == 1'000 && first.skipped_periods == 0,
         "platform timer uses injected monotonic clock");
  platform.overshoot_ns = 2'500;
  const auto late = timer.wait_next();
  expect(late.scheduled_ns == 2'000 && late.skipped_periods == 2,
         "platform timer skips missed periods without catch-up storm");
  platform.overshoot_ns = 0;
  const auto recovered = timer.wait_next();
  expect(recovered.scheduled_ns == 5'000,
         "platform timer resumes at the next future deadline");
}

void test_safety_policy() {
  rtctrl::safety::SafetyPolicy safety;
  rtctrl::model::SensorFrame state{};
  rtctrl::model::CommandFrame command{};
  command.mode = rtctrl::model::CommandMode::Position;
  command.valid_until_ns = 100;
  expect(safety.evaluate(state, command, 50) == rtctrl::safety::SafetyDecision::Accept,
         "valid command accepted");
  expect(safety.evaluate(state, command, 101) ==
             rtctrl::safety::SafetyDecision::CommandExpired,
         "expired command rejected");
  command.valid_until_ns = 200;
  command.effort[0] = std::numeric_limits<double>::quiet_NaN();
  expect(safety.evaluate(state, command, 100) ==
             rtctrl::safety::SafetyDecision::InvalidNumber,
         "NaN rejected");
}

void test_controller_and_hal() {
  rtctrl::model::SensorFrame state{};
  rtctrl::control::JointPd controller;
  controller.reset(state);
  rtctrl::control::ControlContext context{};
  context.now_ns = 1'000;
  context.command_validity_ns = 10'000;
  context.target.position[0] = 1.0;
  rtctrl::model::CommandFrame command{};
  expect(controller.update(state, context, command), "PD controller update");
  expect(command.mode == rtctrl::model::CommandMode::Position, "PD emits position mode");
  expect(command.effort[0] == 0.0 && command.kp[0] == 40.0 && command.kd[0] == 2.0,
         "PD emits hybrid impedance gains with zero feed-forward effort");

  rtctrl::hal::SimulatedHal hal;
  expect(hal.open_safe(1'000) == rtctrl::hal::HalStatus::Ok, "sim HAL opens safe");
  expect(hal.arm(1'000) == rtctrl::hal::HalStatus::Ok, "sim HAL arms explicitly");
  expect(hal.write(1'000, command) == rtctrl::hal::HalStatus::Ok, "sim HAL write");
  expect(hal.read(2'000'000, state) == rtctrl::hal::HalStatus::Ok, "sim HAL read");
  expect(std::isfinite(state.position[0]), "sim HAL finite state");
  hal.emergency_stop(2'000'000);
  hal.close();
}

rtctrl::protocol::TargetEnvelope make_envelope(std::uint32_t session,
                                               std::uint64_t sequence) {
  rtctrl::protocol::TargetEnvelope envelope{};
  envelope.session_id = session;
  envelope.sequence = sequence;
  envelope.sender_time_ns = sequence * 1'000'000;
  envelope.lease_us = 80'000;
  for (std::size_t i = 0; i < envelope.position.size(); ++i) {
    envelope.position[i] = -0.25 + static_cast<double>(i) * 0.1;
  }
  return envelope;
}

void test_fixed_target_codec() {
  rtctrl::protocol::FixedTargetCodec codec;
  const auto input = make_envelope(17, 23);
  std::array<std::byte, rtctrl::protocol::FixedTargetCodec::kFrameSize> wire{};
  const auto encoded = codec.encode(input, wire.data(), wire.size());
  expect(encoded.status == rtctrl::protocol::CodecStatus::Ok,
         "target frame encodes");
  expect(encoded.produced == rtctrl::protocol::FixedTargetCodec::kFrameSize,
         "target frame size follows the selected joint profile");

  rtctrl::protocol::TargetEnvelope output{};
  const auto decoded = codec.decode(wire.data(), wire.size(), output);
  expect(decoded.status == rtctrl::protocol::CodecStatus::Ok &&
             decoded.consumed == wire.size(),
         "target frame decodes");
  expect(output.session_id == input.session_id && output.sequence == input.sequence &&
             output.sender_time_ns == input.sender_time_ns &&
             output.lease_us == input.lease_us,
         "target metadata round trips");
  for (std::size_t i = 0; i < output.position.size(); ++i) {
    expect(std::abs(output.position[i] - input.position[i]) < 1.0e-6,
           "target position round trips through float wire format");
  }

  for (std::size_t byte = 0; byte < wire.size(); ++byte) {
    auto damaged = wire;
    damaged[byte] ^= std::byte{0x01};
    rtctrl::protocol::TargetEnvelope ignored{};
    expect(codec.decode(damaged.data(), damaged.size(), ignored).status !=
               rtctrl::protocol::CodecStatus::Ok,
           "single-bit corruption is rejected");
  }
}

void test_shared_memory_hal() {
  rtctrl::ipc::SharedMotorRegion region;
  expect(rtctrl::ipc::valid_shared_motor_region(region),
         "shared-memory ABI header matches this joint profile");

  rtctrl::ipc::FeedbackSnapshot feedback{};
  feedback.generation = 7;
  feedback.sample_time_ns = 1'000'000;
  feedback.joints[0].position = 0.4;
  feedback.joints[0].velocity = -0.1;
  feedback.imu.sample_time_ns = feedback.sample_time_ns;
  rtctrl::ipc::publish_feedback(region, feedback);

  rtctrl::hal::SharedMemoryHal hal(region, {5'000'000});
  expect(hal.open_safe(1'000'100) == rtctrl::hal::HalStatus::Ok,
         "shared-memory HAL opens with torque disabled");
  expect(region.motor_enable.load() == 0,
         "opening shared-memory HAL never energizes motors");
  expect(hal.arm(1'000'100) == rtctrl::hal::HalStatus::NotReady,
         "arm is refused before a feedback seed");

  rtctrl::model::SensorFrame state{};
  expect(hal.read(1'000'100, state) == rtctrl::hal::HalStatus::Ok &&
             state.sequence == 7 && state.position[0] == 0.4,
         "feedback snapshot reaches the logical joint model");
  expect(hal.arm(1'000'100) == rtctrl::hal::HalStatus::Ok &&
             region.motor_enable.load() == 1,
         "arm succeeds only after fresh fault-free feedback");

  rtctrl::model::CommandFrame command{};
  command.sequence = 9;
  command.created_time_ns = 1'000'100;
  command.valid_until_ns = 2'000'000;
  command.mode = rtctrl::model::CommandMode::Position;
  command.target_position[0] = 0.5;
  command.kp[0] = 40.0;
  command.kd[0] = 2.0;
  expect(hal.write(1'000'200, command) == rtctrl::hal::HalStatus::Ok,
         "hybrid command publishes to L0 mailbox");
  rtctrl::ipc::CommandSnapshot published{};
  expect(rtctrl::ipc::read_command(region, published) &&
             published.generation == 9 && published.joints[0].position == 0.5 &&
             published.joints[0].kp == 40.0,
         "L0 reads a consistent logical-joint command snapshot");

  hal.emergency_stop(1'000'300);
  expect(region.motor_enable.load() == 0,
         "emergency stop cuts the independent L0 enable line");
  hal.close();
}

void test_posix_shared_memory_lifecycle() {
  std::array<char, 64> name{};
  const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
  (void)std::snprintf(name.data(), name.size(), "/rtctrl-test-%ld-%lld",
                      static_cast<long>(::getpid()), static_cast<long long>(nonce));
  rtctrl::ipc::PosixSharedMemoryRegion owner;
  rtctrl::ipc::PosixSharedMemoryRegion client;
  expect(owner.create_owner(name.data()),
         "L0 creates a new shared-memory region without replacing an old one");
  expect(client.attach(name.data()),
         "controller attaches only after ABI size/version validation");
  if (owner.get() != nullptr && client.get() != nullptr) {
    owner.get()->l0_cycle_counter.store(123, std::memory_order_release);
    expect(client.get()->l0_cycle_counter.load(std::memory_order_acquire) == 123,
           "L0 liveness counter is visible across independent mappings");
  }
  client.close();
  owner.close();

  rtctrl::ipc::PosixSharedMemoryRegion missing;
  expect(!missing.attach(name.data()), "owner cleanup unlinks its exact segment");
}

void test_shared_snapshot_concurrency() {
  rtctrl::ipc::SharedMotorRegion region;
  std::atomic<bool> done{false};
  std::atomic<bool> mismatch{false};
  std::thread writer([&]() {
    rtctrl::ipc::FeedbackSnapshot snapshot{};
    for (std::uint64_t generation = 1; generation <= 10'000; ++generation) {
      snapshot.generation = generation;
      snapshot.sample_time_ns = static_cast<std::int64_t>(generation);
      for (auto& joint : snapshot.joints) {
        joint.position = static_cast<double>(generation);
      }
      rtctrl::ipc::publish_feedback(region, snapshot);
    }
    done.store(true, std::memory_order_release);
  });
  std::thread reader([&]() {
    do {
      rtctrl::ipc::FeedbackSnapshot snapshot{};
      if (rtctrl::ipc::read_feedback(region, snapshot) && snapshot.generation != 0) {
        for (const auto& joint : snapshot.joints) {
          if (joint.position != static_cast<double>(snapshot.generation)) {
            mismatch.store(true, std::memory_order_release);
          }
        }
      }
    } while (!done.load(std::memory_order_acquire));
  });
  writer.join();
  reader.join();
  expect(!mismatch.load(std::memory_order_acquire),
         "concurrent shared feedback reads never expose a torn generation");
}

void test_kernel_mailbox_codec() {
  rtctrl::model::CommandFrame command{};
  command.sequence = 1;
  command.created_time_ns = 100;
  command.valid_until_ns = 1'000;
  command.mode = rtctrl::model::CommandMode::Position;
  command.target_position[0] = 0.25;
  command.kp[0] = 40.0;
  command.kd[0] = 2.0;
  rtctrl_mb_command_frame encoded{};
  expect(rtctrl::ipc::encode_mailbox_command(command, encoded) ==
             rtctrl::ipc::MailboxFrameStatus::Ok &&
             encoded.joint_count == rtctrl::model::kJointCount &&
             encoded.joint[0].position == 0.25F &&
             encoded.flags == RTCTRL_MB_COMMAND_FLAG_POSITION,
         "C++ HAL encodes one fixed command for the C UAPI");
  command.effort[0] = std::numeric_limits<double>::quiet_NaN();
  expect(rtctrl::ipc::encode_mailbox_command(command, encoded) ==
             rtctrl::ipc::MailboxFrameStatus::InvalidFrame,
         "non-finite command is rejected before ioctl submission");

  rtctrl_mb_feedback_frame feedback{};
  feedback.sequence = 7;
  feedback.sample_time_ns = 2'000;
  feedback.device_cycle = 77;
  feedback.joint_count = rtctrl::model::kJointCount;
  feedback.joint[0].position = 0.5F;
  feedback.joint[0].velocity = -0.2F;
  rtctrl::model::SensorFrame state{};
  expect(rtctrl::ipc::decode_mailbox_feedback(feedback, 2'500, 1'000,
                                               state) ==
             rtctrl::ipc::MailboxFrameStatus::Ok &&
             state.sequence == 7 && state.position[0] == 0.5,
         "kernel-staged feedback reaches the logical joint model");
  expect(rtctrl::ipc::decode_mailbox_feedback(feedback, 4'000, 1'000,
                                               state) ==
             rtctrl::ipc::MailboxFrameStatus::Stale,
         "stale kernel feedback is rejected at the HAL boundary");
}

void test_yidong_topology() {
  constexpr auto& topology = rtctrl::profiles::yidong23::kTopology;
  static_assert(topology.valid());
  const auto* waist_pitch = topology.for_logical_joint(13);
  expect(waist_pitch != nullptr && waist_pitch->master_id == 2 &&
             waist_pitch->motor_index == 5 &&
             waist_pitch->calibration.protocol == rtctrl::hal::MotorProtocol::Ti5,
         "Yidong logical joint maps to the reviewed physical EtherCAT slot");
  const auto* left_hip = topology.for_physical_motor(0, 0);
  expect(left_hip != nullptr && left_hip->logical_joint_index == 0 &&
             left_hip->calibration.effort_max == 150.0,
         "motor calibration stays attached to the physical motor route");
}

void test_policy_action_mapper() {
  if constexpr (rtctrl::model::kJointCount >= 2) {
    rtctrl::control::PolicyActionConfig config;
    config.action_count = 2;
    config.logical_joint[0] = 1;
    config.logical_joint[1] = 0;
    config.default_position[0] = -0.2;
    config.default_position[1] = 0.3;
    config.action_scale[0] = 0.5;
    config.action_scale[1] = 0.2;
    config.delta_scale[0] = 0.5;
    config.delta_scale[1] = 0.5;
    rtctrl::control::PolicyActionMapper mapper(config);
    expect(mapper.valid(), "policy joint mapping is validated once at startup");
    const std::array<float, 2> base{2.0F, -0.5F};
    const std::array<float, 2> delta{1.0F, 2.0F};
    rtctrl::model::CommandFrame output{};
    expect(mapper.map(base.data(), delta.data(), 10'000, 5'000, output),
           "base policy and delta-action residual map without allocation");
    expect(std::abs(output.target_position[1] - 0.8) < 1.0e-9,
           "residual action is clipped, scaled and added to nominal pose");
    expect(std::abs(output.target_position[0] - (-0.1)) < 1.0e-9,
           "policy output is remapped into canonical logical joint order");
    auto bad = base;
    bad[0] = std::numeric_limits<float>::quiet_NaN();
    expect(!mapper.map(bad.data(), delta.data(), 20'000, 5'000, output),
           "non-finite policy output is rejected before the HAL boundary");
  }
}

void test_framed_command_source() {
  rtctrl::protocol::FixedTargetCodec codec;
  rtctrl::transport::LoopbackByteTransport link(3);
  rtctrl::transport::FramedSourcePolicy policy{};
  policy.max_lease_us = 25'000;
  rtctrl::transport::FramedCommandSource source(link, codec, policy);
  expect(source.open() == rtctrl::transport::TransportStatus::Ok,
         "framed source opens transport");

  const auto envelope = make_envelope(99, 1);
  std::array<std::byte, rtctrl::protocol::FixedTargetCodec::kFrameSize> wire{};
  const auto encoded = codec.encode(envelope, wire.data(), wire.size());
  expect(encoded.status == rtctrl::protocol::CodecStatus::Ok &&
             link.inject(wire.data(), encoded.produced),
         "fragmented wire frame injected");

  rtctrl::model::ControlTarget target{};
  bool received = false;
  std::int64_t now_ns = 5'000'000'000LL;
  for (int attempt = 0; attempt < 128 && !received; ++attempt) {
    received = source.poll(now_ns, target);
    now_ns += 1'000'000;
  }
  expect(received, "short UART reads reconstruct one frame");
  expect(target.sequence == 1, "decoded sequence reaches runtime model");
  expect(target.valid_until_ns - target.created_time_ns == 25'000'000,
         "wire lease is clamped and converted to receiver clock domain");

  expect(link.inject(wire.data(), wire.size()), "replay injected");
  for (int attempt = 0; attempt < 128 && source.metrics().replayed_frames == 0;
       ++attempt) {
    (void)source.poll(now_ns, target);
    now_ns += 1'000'000;
  }
  expect(source.metrics().replayed_frames == 1, "replayed sequence rejected");

  const std::array<std::byte, 3> garbage{std::byte{0x11}, std::byte{0x22},
                                         std::byte{0x33}};
  auto next = make_envelope(99, 2);
  next.sender_time_ns = envelope.sender_time_ns + 1;
  expect(codec.encode(next, wire.data(), wire.size()).status ==
             rtctrl::protocol::CodecStatus::Ok,
         "next frame encodes");
  expect(link.inject(garbage.data(), garbage.size()) &&
             link.inject(wire.data(), wire.size()),
         "garbage prefix and valid frame injected");
  received = false;
  for (int attempt = 0; attempt < 128 && !received; ++attempt) {
    received = source.poll(now_ns, target);
    now_ns += 1'000'000;
  }
  expect(received && target.sequence == 2, "parser resynchronizes after garbage");
  expect(source.metrics().framing_errors >= garbage.size(),
         "resynchronization is observable in metrics");

  auto foreign = make_envelope(100, 3);
  foreign.sender_time_ns = next.sender_time_ns + 1;
  expect(codec.encode(foreign, wire.data(), wire.size()).status ==
             rtctrl::protocol::CodecStatus::Ok &&
             link.inject(wire.data(), wire.size()),
         "foreign session frame injected");
  for (int attempt = 0; attempt < 128; ++attempt) {
    (void)source.poll(now_ns, target);
    now_ns += 1'000'000;
  }
  expect(source.metrics().session_errors == 1,
         "session change requires an explicit link reset");
  source.close();
}

class OneShotSource final : public rtctrl::transport::ICommandSource {
public:
  bool poll(std::int64_t now_ns, rtctrl::model::ControlTarget& target) noexcept override {
    if (sent_) {
      return false;
    }
    sent_ = true;
    target.sequence = 1;
    target.created_time_ns = now_ns;
    target.valid_until_ns = now_ns + 20'000'000;
    target.position[0] = 0.2;
    return true;
  }

private:
  bool sent_{false};
};

class ObservingHal final : public rtctrl::hal::IActuatorHal {
public:
  rtctrl::hal::HalStatus open_safe(std::int64_t) noexcept override {
    return rtctrl::hal::HalStatus::Ok;
  }
  rtctrl::hal::HalStatus arm(std::int64_t) noexcept override {
    armed_.store(true);
    return rtctrl::hal::HalStatus::Ok;
  }
  rtctrl::hal::HalStatus read(std::int64_t now_ns,
                             rtctrl::model::SensorFrame& output) noexcept override {
    output = {};
    output.sequence = ++sequence_;
    output.sample_time_ns = now_ns;
    return rtctrl::hal::HalStatus::Ok;
  }
  rtctrl::hal::HalStatus write(std::int64_t,
                              const rtctrl::model::CommandFrame& input) noexcept override {
    if (!armed_.load()) {
      return rtctrl::hal::HalStatus::NotReady;
    }
    if (input.mode == rtctrl::model::CommandMode::Position) {
      ++position_writes;
    } else {
      ++safe_writes;
    }
    return rtctrl::hal::HalStatus::Ok;
  }
  void emergency_stop(std::int64_t) noexcept override {
    armed_.store(false);
    ++safe_calls;
  }
  void close() noexcept override {}

  std::atomic<int> position_writes{0};
  std::atomic<int> safe_writes{0};
  std::atomic<int> safe_calls{0};

private:
  std::atomic<bool> armed_{false};
  std::uint64_t sequence_{0};
};

void test_target_lease() {
  rtctrl::runtime::RuntimeConfig config{};
  config.lock_memory = false;
  config.arm_actuation = true;
  config.io_thread.priority = 0;
  config.control_thread.priority = 0;
  config.target_validity_ns = 200'000'000;
  ObservingHal hal;
  rtctrl::control::JointPd controller;
  OneShotSource source;
  rtctrl::safety::SafetyPolicy safety;
  rtctrl::platform::PosixRealtimePlatform platform;
  rtctrl::runtime::RealtimeEngine engine(config, platform, hal, controller, source, safety);
  expect(engine.start(), "runtime starts with non-RT test policy");
  std::this_thread::sleep_for(std::chrono::milliseconds(120));
  engine.request_stop();
  engine.join();
  expect(hal.position_writes.load() > 0, "fresh target produces active commands");
  expect(hal.safe_writes.load() > 0,
         "transport target lease overrides the longer runtime lease");
  expect(!engine.report().fault_latched, "target expiry degrades without hardware fault latch");
}

}  // namespace

int main() {
  test_spsc_ring();
  test_platform_independent_timer();
  test_safety_policy();
  test_controller_and_hal();
  test_fixed_target_codec();
  test_shared_memory_hal();
  test_posix_shared_memory_lifecycle();
  test_shared_snapshot_concurrency();
  test_kernel_mailbox_codec();
  test_yidong_topology();
  test_policy_action_mapper();
  test_framed_command_source();
  test_target_lease();
  if (failures == 0) {
    std::cout << "all tests passed\n";
  }
  return failures == 0 ? 0 : 1;
}
