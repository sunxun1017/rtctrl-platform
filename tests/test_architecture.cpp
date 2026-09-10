#include "rtctrl/adapters/posix/posix_realtime.hpp"
#include "rtctrl/bridge/target_arbiter.hpp"
#include "rtctrl/bridge/vision_interlock.hpp"
#include "rtctrl/control/joint_pd.hpp"
#include "rtctrl/hal/actuator_hal.hpp"
#include "rtctrl/runtime/realtime_engine.hpp"

#include <atomic>
#include <chrono>
#include <iostream>
#include <limits>
#include <thread>

namespace {
int failures = 0;
void expect(bool condition, const char* reason) {
    if (!condition) {
        ++failures;
        std::cerr << reason << '\n';
    }
}
struct Ingress : rtctrl::runtime::ITargetIngress {
    bool available{true};
    unsigned writes{0};
    rtctrl::model::ControlTarget last{};
    bool try_submit(const rtctrl::model::ControlTarget& target) noexcept override {
        if (!available) {
            return false;
        }
        ++writes;
        last = target;
        return true;
    }
};
struct Source : rtctrl::bridge::ICommandSource {
    bool pending{false};
    rtctrl::model::ControlTarget next{};
    bool poll(std::int64_t, rtctrl::model::ControlTarget& target) noexcept override {
        if (!pending) {
            return false;
        }
        pending = false;
        target = next;
        return true;
    }
    void send(std::uint64_t sequence, std::int64_t created, std::int64_t expires) {
        next = {};
        next.sequence = sequence;
        next.created_time_ns = created;
        next.valid_until_ns = expires;
        pending = true;
    }
};
struct Lifecycle : rtctrl::runtime::ILifecycleControl {
    unsigned disarms{0};
    void request_disarm() noexcept override {
        ++disarms;
    }
    void request_stop() noexcept override {}
    rtctrl::runtime::RuntimeState state() const noexcept override {
        return rtctrl::runtime::RuntimeState::Ready;
    }
};
void arbitration() {
    Ingress ingress;
    Source low, high;
    rtctrl::bridge::TargetArbiter arbiter(ingress, 100);
    expect(arbiter.bind(0, low, 1) && arbiter.bind(1, high, 10),
           "bind independent sources");
    expect(!arbiter.bind(2, high, 20), "one source cannot be polled twice");
    low.send(100, 10, 100);
    high.send(1, 10, 30);
    expect(arbiter.poll(20) && ingress.last.valid_until_ns == 30,
           "priority arbitration");
    expect(!arbiter.poll(21) && ingress.writes == 1,
           "no timestamp refresh for cached source");
    expect(arbiter.poll(31) && ingress.last.sequence == 2 &&
               ingress.last.created_time_ns == 10 &&
               ingress.last.valid_until_ns == 100,
           "fallback preserves original lease and remaps sequence");
    high.send(2, 32, 70);
    ingress.available = false;
    expect(!arbiter.poll(32) && arbiter.backpressure() == 1,
           "bounded ingress backpressure");
    ingress.available = true;
    expect(arbiter.poll(33) && ingress.last.sequence == 3,
           "retry does not consume output sequence");
    high.send(1, 34, 90);
    expect(!arbiter.poll(34) && arbiter.rejected() == 1, "reject source replay");
    high.send(3, 35, 90);
    high.next.position[0] = std::numeric_limits<double>::quiet_NaN();
    expect(!arbiter.poll(35) && arbiter.rejected() == 2, "reject invalid target");
    expect(!arbiter.poll(101), "all stale sources produce no output");
}
void vision() {
    Lifecycle lifecycle;
    rtctrl::bridge::VisionInterlock gate(lifecycle, 7, 100);
    rtctrl::vision::Observation observation{
        1, 7, 1, 10, 80, rtctrl::vision::SceneState::Clear};
    expect(gate.update(observation, 20) && gate.check(79),
           "fresh clear observation");
    expect(!gate.check(80) && lifecycle.disarms == 1, "silence disarms at deadline");
    observation.sequence = 2;
    observation.capture_time_ns = 81;
    observation.valid_until_ns = 100;
    expect(!gate.update(observation, 81),
           "new clear data cannot rearm a tripped gate");
    Lifecycle other;
    rtctrl::bridge::VisionInterlock active(other, 7);
    observation.scene = rtctrl::vision::SceneState::Active;
    expect(!active.update(observation, 81) && other.disarms == 1,
           "active event disarms");
    Lifecycle wrong_session;
    rtctrl::bridge::VisionInterlock session(wrong_session, 9);
    observation.scene = rtctrl::vision::SceneState::Clear;
    expect(!session.update(observation, 81), "session mismatch fails closed");
}
struct Hal : rtctrl::hal::IActuatorHal {
    std::atomic<unsigned> arms{0}, stops{0}, writes{0};
    std::uint64_t sequence{0};
    bool request_driven{false};
    bool arm_pending{false};
    rtctrl::hal::HalStatus open_safe(std::int64_t) noexcept override {
        return rtctrl::hal::HalStatus::Ok;
    }
    rtctrl::hal::HalStatus arm(std::int64_t) noexcept override {
        ++arms;
        arm_pending = true;
        return rtctrl::hal::HalStatus::Ok;
    }
    rtctrl::hal::HalStatus
    read(std::int64_t now, rtctrl::model::SensorFrame& state) noexcept override {
        if (request_driven && sequence > 0 && arms.load() == 0) {
            return rtctrl::hal::HalStatus::NotReady;
        }
        arm_pending = false;
        state = {};
        state.sequence = ++sequence;
        state.sample_time_ns = now;
        return rtctrl::hal::HalStatus::Ok;
    }
    rtctrl::hal::HalStatus
    write(std::int64_t, const rtctrl::model::CommandFrame&) noexcept override {
        if (arm_pending) {
            return rtctrl::hal::HalStatus::IoError;
        }
        ++writes;
        return rtctrl::hal::HalStatus::Ok;
    }
    void emergency_stop(std::int64_t) noexcept override {
        ++stops;
    }
    void close() noexcept override {}
};
template <class Predicate> bool eventually(Predicate predicate) {
    const auto until = std::chrono::steady_clock::now() + std::chrono::seconds(1);
    while (!predicate() && std::chrono::steady_clock::now() < until) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    return predicate();
}
class RejectedScheduler final : public rtctrl::platform::IRealtimePlatform {
  public:
    std::int64_t now_ns() const noexcept override {
        return clock_.now_ns();
    }
    rtctrl::platform::MemoryLockReport lock_process_memory() noexcept override {
        return {};
    }
    rtctrl::platform::ThreadSetupReport configure_current_thread(
        const rtctrl::platform::ThreadConfig&) noexcept override {
        return {};
    }
    void prefault_stack() noexcept override {}
    int sleep_until(std::int64_t deadline) noexcept override {
        return clock_.sleep_until(deadline);
    }

  private:
    rtctrl::platform::PosixRealtimePlatform clock_;
};
void startup_gate() {
    rtctrl::runtime::RuntimeConfig config;
    config.lock_memory = false;
    config.arm_actuation = true;
    config.io_thread.priority = 0;
    config.control_thread.priority = 1;
    config.control_thread.strict = true;
    RejectedScheduler platform;
    Hal hal;
    rtctrl::control::JointPd controller;
    rtctrl::safety::SafetyPolicy safety;
    rtctrl::runtime::RealtimeEngine engine(
        config, platform, hal, controller, safety);
    expect(!engine.start(), "rejected control scheduler fails startup");
    expect(hal.arms == 0 && hal.writes == 0,
           "scheduler failure never energizes hardware");
    expect(engine.report().fatal_startup_error,
           "startup failure remains observable");
}
void request_response_startup() {
    rtctrl::runtime::RuntimeConfig config;
    config.lock_memory = false;
    config.arm_actuation = true;
    config.io_thread.priority = config.control_thread.priority = 0;
    config.state_validity_ns = 100'000'000;
    Hal hal;
    hal.request_driven = true;
    rtctrl::platform::PosixRealtimePlatform platform;
    rtctrl::control::JointPd controller;
    rtctrl::safety::SafetyPolicy safety;
    rtctrl::runtime::RealtimeEngine engine(
        config, platform, hal, controller, safety);
    expect(engine.start(), "start request/response HAL");
    rtctrl::model::ControlTarget target;
    target.sequence = 1;
    target.created_time_ns = platform.now_ns();
    expect(engine.try_submit(target), "submit first request/response target");
    expect(
        eventually([&] { return hal.writes.load() > 0; }),
        "startup sample permits arm; first read after arm precedes command write");
    engine.request_stop();
    engine.join();
    expect(!engine.report().fault_latched,
           "half-duplex arm handshake does not fault");
}
void runtime() {
    rtctrl::runtime::RuntimeConfig config;
    config.lock_memory = false;
    config.arm_actuation = true;
    config.io_thread.priority = config.control_thread.priority = 0;
    config.target_validity_ns = 1'000'000'000;
    Hal hal;
    rtctrl::platform::PosixRealtimePlatform platform;
    rtctrl::control::JointPd controller;
    rtctrl::safety::SafetyPolicy safety;
    rtctrl::runtime::RealtimeEngine engine(
        config, platform, hal, controller, safety);
    expect(engine.start(), "start runtime");
    expect(!engine.start(), "second start rejected without corrupting live state");
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    expect(hal.arms == 0 && hal.writes == 0,
           "startup permission alone never arms hardware");
    rtctrl::model::ControlTarget target;
    target.sequence = 1;
    target.created_time_ns = platform.now_ns();
    expect(engine.try_submit(target), "external ingress connected");
    expect(eventually([&] { return hal.writes.load() > 0; }),
           "fresh target arms and executes");
    rtctrl::model::SensorFrame snapshot;
    expect(engine.try_read_latest(snapshot) && snapshot.sequence > 0,
           "snapshot port connected");
    rtctrl::bridge::VisionInterlock gate(engine, 1);
    expect(!gate.check(platform.now_ns()), "missing vision data requests disarm");
    expect(eventually([&] { return hal.stops.load() > 0; }),
           "I/O owner executes disarm");
    const auto writes = hal.writes.load();
    expect(!engine.try_submit(target), "terminal disarm closes ingress");
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    expect(hal.writes.load() == writes && hal.arms == 1,
           "no writes or rearm after disarm");
    engine.request_stop();
    engine.join();
    expect(engine.state() == rtctrl::runtime::RuntimeState::Stopped,
           "joined lifecycle");
    expect(!engine.report().fault_latched,
           "requested disarm is not a hardware fault");
}
} // namespace
int main() {
    arbitration();
    vision();
    startup_gate();
    request_response_startup();
    runtime();
    return failures ? 1 : 0;
}
