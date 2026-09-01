#include "rtctrl/platform/posix_realtime.hpp"
#include "rtctrl/runtime/metrics.hpp"

#include <cstdlib>
#include <iomanip>
#include <iostream>

namespace {

double ns_to_us(std::int64_t value) { return static_cast<double>(value) / 1000.0; }

long long env_integer(const char* name, long long fallback) {
  const char* value = std::getenv(name);
  if (value == nullptr || *value == '\0') {
    return fallback;
  }
  char* end = nullptr;
  const auto parsed = std::strtoll(value, &end, 10);
  return end != value && *end == '\0' ? parsed : fallback;
}

}  // namespace

int main(int argc, char** argv) {
  const int duration_seconds = argc > 1 ? std::max(1, std::atoi(argv[1])) : 5;
  const int period_us = argc > 2 ? std::max(100, std::atoi(argv[2])) : 1000;
  const int cpu = argc > 3 ? std::atoi(argv[3]) : -1;
  const int priority = argc > 4 ? std::atoi(argv[4]) : 80;

  rtctrl::platform::PosixRealtimePlatform platform;
  const auto memory = platform.lock_process_memory();
  platform.prefault_stack();
  const auto setup = platform.configure_current_thread({"rt-bench", cpu, priority, false});
  rtctrl::platform::PeriodicTimer timer(platform,
                                        static_cast<std::int64_t>(period_us) * 1000LL);
  rtctrl::runtime::LoopMetrics metrics{};
  const auto end_ns = platform.now_ns() +
                      static_cast<std::int64_t>(duration_seconds) * 1'000'000'000LL;
  while (platform.now_ns() < end_ns) {
    const auto sample = timer.wait_next();
    if (sample.wait_error != 0) {
      ++metrics.io_errors;
      break;
    }
    metrics.record_wakeup(sample.actual_ns - sample.scheduled_ns, sample.skipped_periods);
  }

  const auto max_jitter_us = env_integer("RTCTRL_MAX_JITTER_US", -1);
  const auto max_skipped = env_integer("RTCTRL_MAX_SKIPPED_PERIODS", -1);
  const bool require_fifo = env_integer("RTCTRL_REQUIRE_FIFO", 0) != 0;
  const bool require_mlock = env_integer("RTCTRL_REQUIRE_MLOCK", 0) != 0;
  const bool passed =
      metrics.io_errors == 0 &&
      (max_jitter_us < 0 || metrics.max_jitter_ns <= max_jitter_us * 1000LL) &&
      (max_skipped < 0 ||
       metrics.skipped_periods <= static_cast<std::uint64_t>(max_skipped)) &&
      (!require_fifo || setup.fifo_active) && (!require_mlock || memory.active);

  std::cout << std::fixed << std::setprecision(1)
            << "{\n  \"environment\": \"host functional baseline; verify target kernel and hardware separately\",\n"
            << "  \"period_target_us\": " << period_us << ",\n"
            << "  \"samples\": " << metrics.samples << ",\n"
            << "  \"jitter_p50_us\": " << ns_to_us(metrics.percentile_ns(0.50)) << ",\n"
            << "  \"jitter_p99_us\": " << ns_to_us(metrics.percentile_ns(0.99)) << ",\n"
            << "  \"jitter_max_us\": " << ns_to_us(metrics.max_jitter_ns) << ",\n"
            << "  \"skipped_periods\": " << metrics.skipped_periods << ",\n"
            << "  \"histogram_overflows\": " << metrics.histogram_overflows << ",\n"
            << "  \"wait_errors\": " << metrics.io_errors << ",\n"
            << "  \"scheduler_mode\": \"" << (setup.fifo_active ? "SCHED_FIFO" : "fallback")
            << "\",\n  \"scheduler_errno\": " << setup.scheduler_error
            << ",\n  \"affinity_errno\": " << setup.affinity_error
            << ",\n  \"memory_lock\": " << (memory.active ? "true" : "false")
            << ",\n  \"memory_lock_errno\": " << memory.error
            << ",\n  \"acceptance_passed\": " << (passed ? "true" : "false") << "\n}\n";
  return passed ? 0 : 4;
}
