#include "rtctrl/control/joint_pd.hpp"
#include "rtctrl/hal/simulated_hal.hpp"
#include "rtctrl/platform/posix_realtime.hpp"
#include "rtctrl/runtime/realtime_engine.hpp"
#include "rtctrl/safety/safety_policy.hpp"
#include "rtctrl/transport/loopback_source.hpp"

#include <chrono>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <thread>

namespace {

volatile std::sig_atomic_t stop_requested = 0;

extern "C" void handle_stop_signal(int) {
    stop_requested = 1;
}

double ns_to_us(std::int64_t value) {
    return static_cast<double>(value) / 1000.0;
}

struct Options {
    int duration_seconds{5};
    int io_cpu{-1};
    int control_cpu{-1};
    int io_priority{80};
    int control_priority{70};
    bool strict_rt{false};
    bool lock_memory{true};
    bool arm_actuation{false};
    int fault_after_ms{0};
    bool help_requested{false};
};

void print_help() {
    std::cout << "rtctrl_demo [--duration SEC] [--io-cpu N] [--control-cpu N]\n"
                 "            [--io-priority N] [--control-priority N] [--strict-rt]\n"
                 "            [--arm] [--no-mlock] [--fault-after-ms N]\n";
}

bool parse_int(int argc, char** argv, int& index, int& output) {
    if (index + 1 >= argc) {
        return false;
    }
    output = std::atoi(argv[++index]);
    return true;
}

bool parse_options(int argc, char** argv, Options& options) {
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--duration") == 0 &&
            parse_int(argc, argv, i, options.duration_seconds)) {
        } else if (std::strcmp(argv[i], "--io-cpu") == 0 &&
                   parse_int(argc, argv, i, options.io_cpu)) {
        } else if (std::strcmp(argv[i], "--control-cpu") == 0 &&
                   parse_int(argc, argv, i, options.control_cpu)) {
        } else if (std::strcmp(argv[i], "--io-priority") == 0 &&
                   parse_int(argc, argv, i, options.io_priority)) {
        } else if (std::strcmp(argv[i], "--control-priority") == 0 &&
                   parse_int(argc, argv, i, options.control_priority)) {
        } else if (std::strcmp(argv[i], "--fault-after-ms") == 0 &&
                   parse_int(argc, argv, i, options.fault_after_ms)) {
        } else if (std::strcmp(argv[i], "--strict-rt") == 0) {
            options.strict_rt = true;
        } else if (std::strcmp(argv[i], "--arm") == 0) {
            options.arm_actuation = true;
        } else if (std::strcmp(argv[i], "--no-mlock") == 0) {
            options.lock_memory = false;
        } else if (std::strcmp(argv[i], "--help") == 0) {
            print_help();
            options.help_requested = true;
            return true;
        } else {
            std::cerr << "invalid argument: " << argv[i] << '\n';
            return false;
        }
    }
    return options.duration_seconds > 0 && options.io_priority >= 0 &&
           options.control_priority >= 0;
}

void print_loop(const char* name, const rtctrl::runtime::LoopMetrics& metrics) {
    std::cout << name << ": samples=" << metrics.samples
              << " p50_jitter_us=" << ns_to_us(metrics.percentile_ns(0.50))
              << " p99_jitter_us=" << ns_to_us(metrics.percentile_ns(0.99))
              << " max_jitter_us=" << ns_to_us(metrics.max_jitter_ns)
              << " max_exec_us=" << ns_to_us(metrics.max_execution_ns)
              << " skipped_periods=" << metrics.skipped_periods
              << " histogram_overflows=" << metrics.histogram_overflows
              << " queue_drops=" << metrics.queue_drops << '\n';
}

} // namespace

int main(int argc, char** argv) {
    Options options{};
    if (!parse_options(argc, argv, options)) {
        return 2;
    }
    if (options.help_requested) {
        return 0;
    }

    std::signal(SIGINT, handle_stop_signal);
    std::signal(SIGTERM, handle_stop_signal);

    rtctrl::runtime::RuntimeConfig config{};
    config.lock_memory = options.lock_memory;
    config.arm_actuation = options.arm_actuation;
    config.io_thread = {"rt-io", options.io_cpu, options.io_priority, options.strict_rt};
    config.control_thread = {"rt-control", options.control_cpu, options.control_priority,
                             options.strict_rt};

    rtctrl::hal::SimulatedHalConfig hal_config{};
    hal_config.fault_after_ns = static_cast<std::int64_t>(options.fault_after_ms) * 1'000'000LL;
    rtctrl::hal::SimulatedHal hal(hal_config);
    rtctrl::platform::PosixRealtimePlatform platform;
    rtctrl::control::JointPd controller;
    rtctrl::transport::LoopbackSource source;
    rtctrl::safety::SafetyPolicy safety;
    rtctrl::runtime::RealtimeEngine engine(config, platform, hal, controller, source, safety);

    if (!engine.start()) {
        std::cerr << "failed to start runtime\n";
        return 1;
    }
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::seconds(options.duration_seconds);
    while (stop_requested == 0 && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    engine.request_stop();
    engine.join();

    const auto report = engine.report();
    std::cout << std::fixed << std::setprecision(1);
    std::cout << "scheduler: io=" << (report.io_setup.fifo_active ? "SCHED_FIFO" : "fallback")
              << " control=" << (report.control_setup.fifo_active ? "SCHED_FIFO" : "fallback")
              << " mlock=" << (report.memory.active ? "active" : "fallback") << '\n';
    print_loop("io_1khz", report.io_metrics);
    print_loop("control_200hz", report.control_metrics);
    std::cout << "safety_interventions=" << report.safety_interventions
              << " stale_commands=" << report.io_metrics.stale_commands
              << " io_errors=" << report.io_metrics.io_errors
              << " fault_latched=" << (report.fault_latched ? "true" : "false") << '\n';
    return report.fatal_startup_error ? 3 : 0;
}
