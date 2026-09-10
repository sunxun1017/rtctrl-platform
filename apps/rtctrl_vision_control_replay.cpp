#include "rtctrl/bridge/target_arbiter.hpp"
#include "rtctrl/bridge/vision_interlock.hpp"
#include "rtctrl/control/joint_pd.hpp"
#include "rtctrl/hal/simulated_hal.hpp"
#include "rtctrl/platform/posix_realtime.hpp"
#include "rtctrl/runtime/realtime_engine.hpp"
#include "rtctrl/transport/loopback_source.hpp"

#include <chrono>
#include <csignal>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {
volatile std::sig_atomic_t stopped = 0;
extern "C" void stop_replay(int) {
    stopped = 1;
}
struct Event {
    std::int64_t offset_ms;
    std::int64_t ttl_ms;
    rtctrl::vision::SceneState scene;
};
bool load(const char* path, std::vector<Event>& events) {
    std::ifstream file(path);
    if (!file) {
        return false;
    }
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }
        std::istringstream input(line);
        Event event{};
        std::string scene, extra;
        if (!(input >> event.offset_ms >> event.ttl_ms >> scene) ||
            (input >> extra) || event.offset_ms < 0 || event.offset_ms > 60'000 ||
            event.ttl_ms <= 0 || event.ttl_ms > 100 ||
            (!events.empty() && event.offset_ms <= events.back().offset_ms) ||
            events.size() >= 4096) {
            return false;
        }
        if (scene == "clear") {
            event.scene = rtctrl::vision::SceneState::Clear;
        } else if (scene == "active") {
            event.scene = rtctrl::vision::SceneState::Active;
        } else if (scene == "unknown") {
            event.scene = rtctrl::vision::SceneState::Unknown;
        } else if (scene == "fault") {
            event.scene = rtctrl::vision::SceneState::Fault;
        } else {
            return false;
        }
        events.push_back(event);
    }
    return !file.bad() && !events.empty() && events.front().offset_ms == 0;
}
} // namespace

int main(int argc, char** argv) {
    if (argc < 2 || argc > 3 || (argc == 3 && std::string(argv[2]) != "--arm")) {
        std::cerr << "Usage: rtctrl_vision_control_replay EVENTS [--arm]\n"
                     "EVENTS: offset_ms ttl_ms clear|active|unknown|fault; "
                     "simulated HAL only.\n";
        return 2;
    }
    std::vector<Event> events;
    if (!load(argv[1], events)) {
        std::cerr << "invalid replay file\n";
        return 2;
    }
    std::signal(SIGINT, stop_replay);
    std::signal(SIGTERM, stop_replay);
    rtctrl::runtime::RuntimeConfig config;
    config.lock_memory = false;
    config.arm_actuation = argc == 3;
    config.io_thread.priority = config.control_thread.priority = 0;
    rtctrl::platform::PosixRealtimePlatform platform;
    rtctrl::hal::SimulatedHal hal;
    rtctrl::control::JointPd controller;
    rtctrl::safety::SafetyPolicy safety;
    rtctrl::runtime::RealtimeEngine engine(
        config, platform, hal, controller, safety);
    rtctrl::transport::LoopbackSource source;
    rtctrl::bridge::TargetArbiter targets(engine);
    rtctrl::bridge::VisionInterlock interlock(engine, 1);
    if (!targets.bind(0, source, 0)) {
        return 2;
    }
    const auto begin = platform.now_ns();
    auto publish = [&](std::size_t index) {
        const auto& event = events[index];
        const auto capture = begin + event.offset_ms * 1'000'000;
        return interlock.update({1,
                                 1,
                                 index + 1,
                                 capture,
                                 capture + event.ttl_ms * 1'000'000,
                                 event.scene},
                                platform.now_ns());
    };
    bool tripped = !publish(0);
    if (!engine.start()) {
        std::cerr << "runtime start failed\n";
        return 1;
    }
    std::size_t next = 1;
    auto next_target = begin;
    const auto end = begin + (events.back().offset_ms + 120) * 1'000'000;
    while (!stopped && platform.now_ns() < end) {
        const auto now = platform.now_ns();
        while (next < events.size() &&
               now >= begin + events[next].offset_ms * 1'000'000) {
            if (!publish(next++)) {
                tripped = true;
            }
        }
        if (!interlock.check(now)) {
            tripped = true;
        }
        if (now >= next_target) {
            (void)targets.poll(now);
            next_target = now + 20'000'000;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    engine.request_stop();
    engine.join();
    const auto report = engine.report();
    std::cout << "simulated=true vision_disarmed=" << (tripped ? "true" : "false")
              << " fault_latched=" << (report.fault_latched ? "true" : "false")
              << '\n';
    return report.fatal_startup_error || report.fault_latched ? 1 : 0;
}
