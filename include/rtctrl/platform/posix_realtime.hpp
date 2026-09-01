#pragma once

#include "rtctrl/platform/realtime_platform.hpp"

namespace rtctrl::platform {

class PosixRealtimePlatform final : public IRealtimePlatform {
public:
  std::int64_t now_ns() const noexcept override;
  MemoryLockReport lock_process_memory() noexcept override;
  ThreadSetupReport configure_current_thread(const ThreadConfig& config) noexcept override;
  void prefault_stack() noexcept override;
  int sleep_until(std::int64_t absolute_deadline_ns) noexcept override;
};

}  // namespace rtctrl::platform
