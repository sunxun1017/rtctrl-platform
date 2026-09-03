#include "rtctrl/platform/realtime_platform.hpp"

namespace rtctrl::platform {

PeriodicTimer::PeriodicTimer(IRealtimePlatform& platform, std::int64_t period_ns) noexcept
    : platform_(platform), period_ns_(period_ns), next_ns_(platform.now_ns() + period_ns) {}

WakeupSample PeriodicTimer::wait_next() noexcept {
    const auto scheduled = next_ns_;
    const int wait_error = platform_.sleep_until(scheduled);
    const auto actual = platform_.now_ns();
    std::uint64_t skipped = 0;
    if (actual > scheduled + period_ns_) {
        skipped = static_cast<std::uint64_t>((actual - scheduled) / period_ns_);
    }
    next_ns_ = scheduled + static_cast<std::int64_t>(skipped + 1U) * period_ns_;
    return WakeupSample{scheduled, actual, skipped, wait_error};
}

} // namespace rtctrl::platform
