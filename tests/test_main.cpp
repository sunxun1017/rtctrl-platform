#include "rtctrl/control/joint_pd.hpp"
#include "rtctrl/hal/simulated_hal.hpp"
#include "rtctrl/ipc/spsc_ring.hpp"
#include "rtctrl/platform/posix_realtime.hpp"
#include "rtctrl/protocol/fixed_target_codec.hpp"
#include "rtctrl/runtime/realtime_engine.hpp"
#include "rtctrl/safety/safety_policy.hpp"
#include "rtctrl/transport/command_source.hpp"
#include "rtctrl/transport/framed_command_source.hpp"
#include "rtctrl/transport/loopback_byte_transport.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <thread>

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
  expect(command.effort[0] > 0.0 && command.effort[0] <= 20.0, "PD effort saturated");

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
  expect(encoded.produced == 64, "v1 target frame has stable 64-byte ABI");

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
  for (int attempt = 0; attempt < 32 && !received; ++attempt) {
    received = source.poll(now_ns, target);
    now_ns += 1'000'000;
  }
  expect(received, "short UART reads reconstruct one frame");
  expect(target.sequence == 1, "decoded sequence reaches runtime model");
  expect(target.valid_until_ns - target.created_time_ns == 25'000'000,
         "wire lease is clamped and converted to receiver clock domain");

  expect(link.inject(wire.data(), wire.size()), "replay injected");
  for (int attempt = 0; attempt < 32 && source.metrics().replayed_frames == 0;
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
  for (int attempt = 0; attempt < 32 && !received; ++attempt) {
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
  for (int attempt = 0; attempt < 32; ++attempt) {
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
  test_framed_command_source();
  test_target_lease();
  if (failures == 0) {
    std::cout << "all tests passed\n";
  }
  return failures == 0 ? 0 : 1;
}
