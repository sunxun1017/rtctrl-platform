#pragma once

#include <cstdint>

namespace rtctrl::platform {

struct ThreadConfig {
  const char* name{"rtctrl"};
  int cpu{-1};
  int priority{0};
  bool strict{false};
};

struct ThreadSetupReport {
  bool affinity_active{false};
  bool fifo_active{false};
  int affinity_error{0};
  int scheduler_error{0};
};

struct MemoryLockReport {
  bool active{false};
  int error{0};
};

struct WakeupSample {
  std::int64_t scheduled_ns{0};
  std::int64_t actual_ns{0};
  std::uint64_t skipped_periods{0};
  int wait_error{0};
};

class IRealtimePlatform {
public:
  virtual ~IRealtimePlatform() = default;

  virtual std::int64_t now_ns() const noexcept = 0;
  virtual MemoryLockReport lock_process_memory() noexcept = 0;
  virtual ThreadSetupReport configure_current_thread(const ThreadConfig& config) noexcept = 0;
  virtual void prefault_stack() noexcept = 0;
  virtual int sleep_until(std::int64_t absolute_deadline_ns) noexcept = 0;
};

class PeriodicTimer {
public:
  PeriodicTimer(IRealtimePlatform& platform, std::int64_t period_ns) noexcept;
  WakeupSample wait_next() noexcept;

private:
  IRealtimePlatform& platform_;
  std::int64_t period_ns_;
  std::int64_t next_ns_;
};

}  // namespace rtctrl::platform
