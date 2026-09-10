#pragma once

#include "rtctrl/control/controller.hpp"
#include "rtctrl/hal/actuator_hal.hpp"
#include "rtctrl/ipc/spsc_ring.hpp"
#include "rtctrl/runtime/metrics.hpp"
#include "rtctrl/runtime/realtime_platform.hpp"
#include "rtctrl/runtime/runtime_ports.hpp"
#include "rtctrl/safety/safety_policy.hpp"

#include <atomic>
#include <cstdint>
#include <thread>

namespace rtctrl::runtime {

struct RuntimeConfig {
    std::int64_t io_period_ns{1'000'000};
    std::int64_t control_period_ns{5'000'000};
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

class RealtimeEngine final : public runtime::ITargetIngress,
                             public runtime::IStateSnapshot,
                             public runtime::ILifecycleControl {
  public:
    RealtimeEngine(RuntimeConfig config,
                   platform::IRealtimePlatform& platform,
                   hal::IActuatorHal& hal,
                   control::IController& controller,
                   safety::SafetyPolicy& safety) noexcept;
    ~RealtimeEngine();

    RealtimeEngine(const RealtimeEngine&) = delete;
    RealtimeEngine& operator=(const RealtimeEngine&) = delete;

    bool start() noexcept;
    void request_stop() noexcept override;
    void request_disarm() noexcept override;
    runtime::RuntimeState state() const noexcept override;
    bool try_submit(const model::ControlTarget& target) noexcept override;
    bool try_read_latest(model::SensorFrame& state) const noexcept override;
    void join() noexcept;
    RuntimeReport report() const noexcept;

  private:
    void io_loop() noexcept;
    void control_loop() noexcept;

    RuntimeConfig config_;
    platform::IRealtimePlatform& platform_;
    hal::IActuatorHal& hal_;
    control::IController& controller_;
    safety::SafetyPolicy& safety_;

    ipc::SpscRing<model::SensorFrame, 256> states_{};
    ipc::SpscRing<model::CommandFrame, 64> commands_{};
    ipc::SpscRing<model::ControlTarget, 32> targets_{};

    mutable ipc::SpscRing<model::SensorFrame, 32> snapshots_{};
    mutable model::SensorFrame last_snapshot_{};
    mutable bool has_snapshot_{false};
    std::atomic<bool> disarm_requested_{false};
    std::atomic<bool> armed_{false};
    std::atomic<bool> fault_latched_{false};
    std::atomic<runtime::RuntimeState> lifecycle_{runtime::RuntimeState::Created};
    std::atomic<bool> stop_{false};
    std::atomic<bool> running_{false};
    std::atomic<bool> fatal_startup_error_{false};
    std::atomic<int> io_startup_state_{0};
    std::atomic<int> control_startup_state_{0};
    bool started_once_{false};
    std::thread io_thread_{};
    std::thread control_thread_{};
    RuntimeReport report_{};
};

} // namespace rtctrl::runtime
