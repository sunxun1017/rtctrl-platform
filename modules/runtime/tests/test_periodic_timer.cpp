#include "rtctrl/runtime/periodic_timer.hpp"
#include <iostream>

namespace {
int failures = 0;
void expect(bool condition, const char* message) {
    if (!condition) {
        ++failures;
        std::cerr << "FAIL: " << message << '\n';
    }
}

class FakeRealtimePlatform final : public rtctrl::platform::IRealtimePlatform {
  public:
    std::int64_t now_ns() const noexcept override {
        return now_;
    }
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

} // namespace
int main() {
    test_platform_independent_timer();
    return failures == 0 ? 0 : 1;
}
