#pragma once
#include "rtctrl/runtime/realtime_platform.hpp"

namespace rtctrl::platform {

class PeriodicTimer {
  public:
    PeriodicTimer(IRealtimePlatform& platform, std::int64_t period_ns) noexcept;
    WakeupSample wait_next() noexcept;

  private:
    IRealtimePlatform& platform_;
    std::int64_t period_ns_;
    std::int64_t next_ns_;
};

} // namespace rtctrl::platform
