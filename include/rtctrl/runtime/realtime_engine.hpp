#pragma once

#include "rtctrl/control/controller.hpp"
#include "rtctrl/hal/actuator_hal.hpp"
#include "rtctrl/ipc/spsc_ring.hpp"
#include "rtctrl/platform/realtime_platform.hpp"
#include "rtctrl/runtime/metrics.hpp"
#include "rtctrl/safety/safety_policy.hpp"
#include "rtctrl/transport/command_source.hpp"

#include <atomic>
#include <cstdint>
#include <thread>

namespace rtctrl::runtime {

struct RuntimeConfig {
  std::int64_t io_period_ns{1'000'000};
  std::int64_t control_period_ns{5'000'000};
  std::int64_t source_period_ns{20'000'000};
  std::int64_t command_validity_ns{15'000'000};
  std::int64_t target_validity_ns{100'000'000};
  std::int64_t state_validity_ns{10'000'000};
  std::int64_t startup_feedback_timeout_ns{1'000'000'000};
  std::int64_t startup_poll_interval_ns{1'000'000};
  bool lock_memory{true};
  bool arm_actuation{false};
  platform::ThreadConfig io_thread{"rt-io", -1, 80, false};
  platform::ThreadConfig control_thread{"rt-control", -1, 70, false};
};

struct RuntimeReport {
  platform::MemoryLockReport memory{};
  platform::ThreadSetupReport io_setup{};
  platform::ThreadSetupReport control_setup{};
  LoopMetrics io_metrics{};
  LoopMetrics control_metrics{};
  std::uint64_t safety_interventions{0};
  bool fault_latched{false};
  bool fatal_startup_error{false};
};

class RealtimeEngine {
public:
  RealtimeEngine(RuntimeConfig config, platform::IRealtimePlatform& platform,
                 hal::IActuatorHal& hal,
                 control::IController& controller, transport::ICommandSource& source,
                 safety::SafetyPolicy& safety) noexcept;
  ~RealtimeEngine();

  RealtimeEngine(const RealtimeEngine&) = delete;
  RealtimeEngine& operator=(const RealtimeEngine&) = delete;

  bool start() noexcept;
  void request_stop() noexcept;
  void join() noexcept;
  RuntimeReport report() const noexcept;

private:
  void io_loop() noexcept;
  void control_loop() noexcept;
  void source_loop() noexcept;

  RuntimeConfig config_;
  platform::IRealtimePlatform& platform_;
  hal::IActuatorHal& hal_;
  control::IController& controller_;
  transport::ICommandSource& source_;
  safety::SafetyPolicy& safety_;

  ipc::SpscRing<model::SensorFrame, 256> states_{};
  ipc::SpscRing<model::CommandFrame, 64> commands_{};
  ipc::SpscRing<model::ControlTarget, 32> targets_{};

  std::atomic<bool> stop_{false};
  std::atomic<bool> running_{false};
  std::atomic<bool> fatal_startup_error_{false};
  std::atomic<int> io_startup_state_{0};
  std::atomic<int> control_startup_state_{0};
  bool started_once_{false};
  std::thread io_thread_{};
  std::thread control_thread_{};
  std::thread source_thread_{};
  RuntimeReport report_{};
};

}  // namespace rtctrl::runtime
